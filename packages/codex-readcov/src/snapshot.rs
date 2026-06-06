use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use serde::Deserialize;
use serde::Serialize;
use std::fs;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use crate::paths::normalize_path;
use crate::rollout::read_metadata;
use crate::rollout::resolve_rollout;
use crate::rollout::rollout_cursor;

const SNAPSHOT_FORMAT: &str = "codex-readcov.snapshot.v1";

#[derive(Debug, Serialize, Deserialize)]
pub(crate) struct Snapshot {
    pub(crate) format: String,
    pub(crate) thread_id: Option<String>,
    pub(crate) rollout: PathBuf,
    pub(crate) cwd: PathBuf,
    pub(crate) line: usize,
    pub(crate) byte_offset: u64,
}

pub(crate) fn create_snapshot(thread_or_rollout: &str) -> Result<Snapshot> {
    let rollout = resolve_rollout(thread_or_rollout)?;
    create_snapshot_from_rollout(&rollout)
}

pub(crate) fn create_snapshot_from_rollout(rollout: &Path) -> Result<Snapshot> {
    let metadata = read_metadata(rollout)?;
    let cwd = metadata
        .cwd
        .context("rollout cwd not found in session_meta")?;
    let cursor = rollout_cursor(rollout)?;
    Ok(Snapshot {
        format: SNAPSHOT_FORMAT.to_string(),
        thread_id: metadata.thread_id,
        rollout: fs::canonicalize(rollout).unwrap_or_else(|_| normalize_path(rollout)),
        cwd,
        line: cursor.line,
        byte_offset: cursor.byte_offset,
    })
}

pub(crate) fn validate_snapshot_pair(from: &Snapshot, to: &Snapshot) -> Result<()> {
    if from.format != SNAPSHOT_FORMAT {
        bail!("unsupported from snapshot format: {}", from.format);
    }
    if to.format != SNAPSHOT_FORMAT {
        bail!("unsupported to snapshot format: {}", to.format);
    }
    if from.rollout != to.rollout {
        bail!("snapshots refer to different rollouts");
    }
    if from.cwd != to.cwd {
        bail!("snapshots refer to different cwd values");
    }
    if from.byte_offset > to.byte_offset {
        bail!("from snapshot is later than to snapshot");
    }
    Ok(())
}

pub(crate) fn read_snapshot_arg(path: &str) -> Result<Snapshot> {
    let input = if path == "-" {
        let mut input = String::new();
        std::io::stdin().read_to_string(&mut input)?;
        input
    } else {
        fs::read_to_string(path).with_context(|| format!("reading {path}"))?
    };
    let snapshot: Snapshot = serde_json::from_str(&input)?;
    if snapshot.format != SNAPSHOT_FORMAT {
        bail!("unsupported snapshot format: {}", snapshot.format);
    }
    Ok(snapshot)
}
