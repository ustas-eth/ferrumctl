use anyhow::Result;
use anyhow::bail;
use codex_shell_command::parse_command::parse_command;
use serde_json::Value;
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io::BufRead;
use std::path::Path;
use std::path::PathBuf;

use crate::paths::resolve_path;
use crate::rollout::parse_rollout_json_line;

#[derive(Debug, Default)]
pub(crate) struct Counts {
    pub(crate) files: BTreeMap<PathBuf, usize>,
    pub(crate) exec_calls: usize,
}

#[derive(Clone, Copy, Debug, Default)]
pub(crate) struct ScanRange {
    from_line: Option<usize>,
    to_line: Option<usize>,
    from_byte: Option<u64>,
    to_byte: Option<u64>,
}

impl ScanRange {
    pub(crate) fn lines(from: Option<usize>, to: Option<usize>) -> Result<Self> {
        if let (Some(from), Some(to)) = (from, to)
            && from > to
        {
            bail!("--from-line must be less than or equal to --to-line");
        }
        Ok(Self {
            from_line: from,
            to_line: to,
            ..Self::default()
        })
    }

    pub(crate) fn bytes(from: u64, to: u64) -> Result<Self> {
        if from > to {
            bail!("from snapshot is later than to snapshot");
        }
        Ok(Self {
            from_byte: Some(from),
            to_byte: Some(to),
            ..Self::default()
        })
    }

    fn contains(self, line_no: usize, byte_start: u64) -> bool {
        if self.from_line.is_some_and(|from| line_no < from) {
            return false;
        }
        if self.to_line.is_some_and(|to| line_no > to) {
            return false;
        }
        if self.from_byte.is_some_and(|from| byte_start < from) {
            return false;
        }
        if self.to_byte.is_some_and(|to| byte_start >= to) {
            return false;
        }
        true
    }
}

pub(crate) fn count_from_exec_calls(
    rollout: &Path,
    cwd: &Path,
    filters: &[PathBuf],
    range: ScanRange,
) -> Result<Counts> {
    let file = fs::File::open(rollout)?;
    let mut reader = std::io::BufReader::new(file);
    let mut line = String::new();
    let mut line_no = 0;
    let mut byte_offset = 0;
    let mut counts = Counts::default();

    loop {
        line.clear();
        let bytes = reader.read_line(&mut line)?;
        if bytes == 0 {
            break;
        }

        line_no += 1;
        let byte_start = byte_offset;
        byte_offset += bytes as u64;
        if !range.contains(line_no, byte_start) {
            continue;
        }

        let Some(value) = parse_rollout_json_line(&line, line_no)? else {
            continue;
        };
        let Some(payload) = value.get("payload") else {
            continue;
        };
        if value.get("type").and_then(Value::as_str) != Some("response_item") {
            continue;
        }
        if payload.get("type").and_then(Value::as_str) != Some("function_call") {
            continue;
        }
        if payload.get("name").and_then(Value::as_str) != Some("exec_command") {
            continue;
        }

        let Some(arguments) = payload.get("arguments").and_then(Value::as_str) else {
            continue;
        };
        let call: Value = serde_json::from_str(arguments)?;
        let Some(cmd) = call.get("cmd").and_then(Value::as_str) else {
            continue;
        };

        counts.exec_calls += 1;
        let workdir = call
            .get("workdir")
            .and_then(Value::as_str)
            .map(|path| resolve_path(cwd, Path::new(path)))
            .unwrap_or_else(|| cwd.to_path_buf());
        let shell = call
            .get("shell")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .or_else(|| env::var("SHELL").ok())
            .unwrap_or_else(|| "bash".to_string());
        let login = call.get("login").and_then(Value::as_bool).unwrap_or(true);
        let flag = if login { "-lc" } else { "-c" };
        let argv = vec![shell, flag.to_string(), cmd.to_string()];

        for parsed in parse_command(&argv) {
            let value = serde_json::to_value(parsed)?;
            count_read_value(&mut counts.files, &value, &workdir, filters);
        }
    }

    Ok(counts)
}

fn count_read_value(
    files: &mut BTreeMap<PathBuf, usize>,
    value: &Value,
    cwd: &Path,
    filters: &[PathBuf],
) {
    if value.get("type").and_then(Value::as_str) != Some("read") {
        return;
    }
    let Some(path) = value.get("path").and_then(Value::as_str) else {
        return;
    };

    let resolved = resolve_path(cwd, Path::new(path));
    if filters.is_empty() || filters.iter().any(|filter| resolved.starts_with(filter)) {
        *files.entry(resolved).or_insert(0) += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::paths::resolve_filters;
    use crate::snapshot::create_snapshot_from_rollout;
    use crate::snapshot::validate_snapshot_pair;
    use std::io::Write;

    struct TempTestDir {
        path: PathBuf,
    }

    impl Drop for TempTestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    fn temp_test_dir(name: &str) -> Result<TempTestDir> {
        let path = env::temp_dir().join(format!(
            "codex-readcov-test-{}-{}",
            name,
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path)?;
        Ok(TempTestDir { path })
    }

    fn append_exec_rollout_event(rollout: &Path, cmd: &str, workdir: Option<&Path>) -> Result<()> {
        let mut call = serde_json::json!({ "cmd": cmd });
        if let Some(workdir) = workdir {
            call["workdir"] = serde_json::json!(workdir);
        }
        let event = serde_json::json!({
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": serde_json::to_string(&call)?,
            },
        });
        let mut file = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(rollout)?;
        writeln!(file, "{}", serde_json::to_string(&event)?)?;
        Ok(())
    }

    fn write_rollout_meta(rollout: &Path, cwd: &Path) -> Result<()> {
        let event = serde_json::json!({
            "type": "session_meta",
            "payload": {
                "id": "00000000-0000-4000-8000-000000000001",
                "cwd": cwd,
            },
        });
        let mut file = fs::File::create(rollout)?;
        writeln!(file, "{}", serde_json::to_string(&event)?)?;
        Ok(())
    }

    #[test]
    fn line_range_is_inclusive() -> Result<()> {
        let range = ScanRange::lines(Some(2), Some(4))?;
        assert!(!range.contains(1, 0));
        assert!(range.contains(2, 0));
        assert!(range.contains(4, 0));
        assert!(!range.contains(5, 0));
        Ok(())
    }

    #[test]
    fn line_range_rejects_reversed_bounds() {
        assert!(ScanRange::lines(Some(4), Some(2)).is_err());
    }

    #[test]
    fn byte_range_is_start_inclusive_end_exclusive() -> Result<()> {
        let range = ScanRange::bytes(10, 20)?;
        assert!(!range.contains(1, 9));
        assert!(range.contains(1, 10));
        assert!(range.contains(1, 19));
        assert!(!range.contains(1, 20));
        Ok(())
    }

    #[test]
    fn byte_range_rejects_reversed_bounds() {
        assert!(ScanRange::bytes(20, 10).is_err());
    }

    #[test]
    fn fixture_rollout_counts_reads_with_filters_and_workdirs() -> Result<()> {
        let root = temp_test_dir("counts")?;
        let cwd = root.path.join("project");
        let nested = cwd.join("src/nested");
        fs::create_dir_all(&nested)?;
        let rollout = root.path.join("rollout.jsonl");
        write_rollout_meta(&rollout, &cwd)?;
        append_exec_rollout_event(&rollout, "cat src/a.rs && sed -n '1,5p' src/b.rs", None)?;
        append_exec_rollout_event(&rollout, "cat ../a.rs", Some(&nested))?;
        append_exec_rollout_event(&rollout, "cat docs/ignored.md", None)?;

        let filters = resolve_filters(&cwd, &[PathBuf::from("src")]);
        let counts = count_from_exec_calls(&rollout, &cwd, &filters, ScanRange::default())?;

        assert_eq!(counts.exec_calls, 3);
        assert_eq!(counts.files.get(&cwd.join("src/a.rs")), Some(&2));
        assert_eq!(counts.files.get(&cwd.join("src/b.rs")), Some(&1));
        assert!(!counts.files.contains_key(&cwd.join("docs/ignored.md")));

        Ok(())
    }

    #[test]
    fn snapshot_byte_window_counts_only_appended_reads() -> Result<()> {
        let root = temp_test_dir("delta")?;
        let cwd = root.path.join("project");
        fs::create_dir_all(cwd.join("src"))?;
        let rollout = root.path.join("rollout.jsonl");
        write_rollout_meta(&rollout, &cwd)?;
        append_exec_rollout_event(&rollout, "cat src/before.rs", None)?;
        let from = create_snapshot_from_rollout(&rollout)?;
        append_exec_rollout_event(&rollout, "cat src/after.rs", None)?;
        let to = create_snapshot_from_rollout(&rollout)?;
        validate_snapshot_pair(&from, &to)?;

        let range = ScanRange::bytes(from.byte_offset, to.byte_offset)?;
        let counts = count_from_exec_calls(&rollout, &cwd, &[], range)?;

        assert_eq!(counts.exec_calls, 1);
        assert!(!counts.files.contains_key(&cwd.join("src/before.rs")));
        assert_eq!(counts.files.get(&cwd.join("src/after.rs")), Some(&1));

        Ok(())
    }
}
