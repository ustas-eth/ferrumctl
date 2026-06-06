use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use serde_json::Value;
use std::env;
use std::fs;
use std::io::BufRead;
use std::path::Path;
use std::path::PathBuf;

#[derive(Debug, Default)]
pub(crate) struct Metadata {
    pub(crate) thread_id: Option<String>,
    pub(crate) cwd: Option<PathBuf>,
}

#[derive(Debug)]
pub(crate) struct RolloutCursor {
    pub(crate) line: usize,
    pub(crate) byte_offset: u64,
}

pub(crate) fn resolve_rollout(value: &str) -> Result<PathBuf> {
    let path = PathBuf::from(value);
    if path.exists() {
        return Ok(path);
    }
    let sessions = env::var_os("CODEX_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".codex")))
        .context("CODEX_HOME or HOME is required to resolve thread ids")?
        .join("sessions");

    let mut matches = Vec::new();
    find_rollouts(&sessions, value, &mut matches)?;
    match matches.len() {
        0 => bail!(
            "no rollout found for thread id {value} under {}",
            sessions.display()
        ),
        1 => Ok(matches.remove(0)),
        _ => bail!("multiple rollouts found for {value}; pass the rollout path"),
    }
}

pub(crate) fn read_metadata(rollout: &Path) -> Result<Metadata> {
    let file = fs::File::open(rollout)?;
    let mut reader = std::io::BufReader::new(file);
    let mut line = String::new();
    let mut line_no = 0;

    loop {
        line.clear();
        let bytes = reader.read_line(&mut line)?;
        if bytes == 0 {
            break;
        }

        line_no += 1;
        let Some(value) = parse_rollout_json_line(&line, line_no)? else {
            continue;
        };
        if value.get("type").and_then(Value::as_str) != Some("session_meta") {
            continue;
        }
        let thread_id = value
            .pointer("/payload/id")
            .and_then(Value::as_str)
            .map(str::to_owned);
        let cwd = value
            .pointer("/payload/cwd")
            .and_then(Value::as_str)
            .map(PathBuf::from);
        return Ok(Metadata { thread_id, cwd });
    }
    Ok(Metadata::default())
}

pub(crate) fn parse_rollout_json_line(line: &str, line_no: usize) -> Result<Option<Value>> {
    match serde_json::from_str(line) {
        Ok(value) => Ok(Some(value)),
        Err(err) if !line.ends_with('\n') && err.is_eof() => Ok(None),
        Err(err) => Err(err).with_context(|| format!("parsing rollout JSON at line {line_no}")),
    }
}

pub(crate) fn rollout_cursor(rollout: &Path) -> Result<RolloutCursor> {
    let file = fs::File::open(rollout)?;
    let mut reader = std::io::BufReader::new(file);
    let mut line = String::new();
    let mut line_count = 0;
    let mut byte_offset = 0;

    loop {
        line.clear();
        let bytes = reader.read_line(&mut line)?;
        if bytes == 0 {
            break;
        }

        let next_line = line_count + 1;
        if parse_rollout_json_line(&line, next_line)?.is_none() {
            break;
        }

        line_count = next_line;
        byte_offset += bytes as u64;
    }

    Ok(RolloutCursor {
        line: line_count,
        byte_offset,
    })
}

fn find_rollouts(dir: &Path, thread_id: &str, matches: &mut Vec<PathBuf>) -> Result<()> {
    if !dir.exists() {
        return Ok(());
    }
    for entry in fs::read_dir(dir).with_context(|| format!("reading {}", dir.display()))? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            find_rollouts(&path, thread_id, matches)?;
            continue;
        }
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if name.starts_with("rollout-") && name.ends_with(".jsonl") && name.contains(thread_id) {
            matches.push(path);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    struct TempRollout {
        path: PathBuf,
    }

    impl Drop for TempRollout {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.path);
        }
    }

    fn temp_rollout(name: &str) -> TempRollout {
        TempRollout {
            path: env::temp_dir().join(format!(
                "codex-readcov-rollout-{}-{}",
                name,
                std::process::id()
            )),
        }
    }

    #[test]
    fn rollout_json_line_allows_valid_final_line_without_newline() -> Result<()> {
        let value = parse_rollout_json_line(r#"{"type":"session_meta"}"#, 1)?;
        assert_eq!(
            value.and_then(|value| value["type"].as_str().map(str::to_owned)),
            Some("session_meta".to_string())
        );
        Ok(())
    }

    #[test]
    fn rollout_json_line_skips_partial_final_line() -> Result<()> {
        let value = parse_rollout_json_line(r#"{"type":"response_item""#, 1)?;
        assert!(value.is_none());
        Ok(())
    }

    #[test]
    fn rollout_json_line_rejects_malformed_complete_line() {
        assert!(parse_rollout_json_line("{\n", 1).is_err());
    }

    #[test]
    fn rollout_cursor_stops_before_partial_final_line() -> Result<()> {
        let rollout = temp_rollout("partial-cursor");
        let complete = r#"{"type":"session_meta"}"#;
        let partial = r#"{"type":"response_item""#;
        let mut file = fs::File::create(&rollout.path)?;
        writeln!(file, "{complete}")?;
        write!(file, "{partial}")?;

        let cursor = rollout_cursor(&rollout.path)?;

        assert_eq!(cursor.line, 1);
        assert_eq!(cursor.byte_offset, (complete.len() + 1) as u64);
        Ok(())
    }

    #[test]
    fn rollout_cursor_counts_valid_final_line_without_newline() -> Result<()> {
        let rollout = temp_rollout("complete-cursor");
        let first = r#"{"type":"session_meta"}"#;
        let second = r#"{"type":"response_item"}"#;
        let mut file = fs::File::create(&rollout.path)?;
        writeln!(file, "{first}")?;
        write!(file, "{second}")?;

        let cursor = rollout_cursor(&rollout.path)?;

        assert_eq!(cursor.line, 2);
        assert_eq!(cursor.byte_offset, (first.len() + 1 + second.len()) as u64);
        Ok(())
    }
}
