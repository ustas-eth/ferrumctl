use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use clap::Args as ClapArgs;
use clap::Parser;
use clap::Subcommand;
use codex_shell_command::parse_command::parse_command;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::env;
use std::ffi::OsString;
use std::fs;
use std::io::BufRead;
use std::io::Read;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

const SNAPSHOT_FORMAT: &str = "codex-readcov.snapshot.v1";

#[derive(Parser, Debug)]
#[command(
    author,
    version,
    about = "Count file read actions in Codex rollout transcripts"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Count reads in a rollout.
    Top(TopArgs),

    /// Print a JSON cursor for the current end of a rollout.
    Snapshot(SnapshotArgs),

    /// Count reads appended between two snapshots, or from one snapshot to now.
    Delta(DeltaArgs),
}

#[derive(ClapArgs, Debug)]
struct TopArgs {
    /// Codex thread id or path to a rollout JSONL file.
    thread_or_rollout: String,

    #[command(flatten)]
    output: OutputOptions,

    /// Start counting at this 1-based rollout line.
    #[arg(long)]
    from_line: Option<usize>,

    /// Stop counting at this 1-based rollout line.
    #[arg(long)]
    to_line: Option<usize>,

    /// Optional path filters. Relative paths are resolved from the rollout cwd.
    paths: Vec<PathBuf>,
}

#[derive(ClapArgs, Debug)]
struct SnapshotArgs {
    /// Codex thread id or path to a rollout JSONL file.
    thread_or_rollout: String,
}

#[derive(ClapArgs, Debug)]
struct DeltaArgs {
    /// Snapshot JSON file, or '-' for stdin.
    from: String,

    /// Later snapshot JSON file. Defaults to the current rollout end.
    #[arg(long)]
    to: Option<String>,

    #[command(flatten)]
    output: OutputOptions,

    /// Optional path filters. Relative paths are resolved from the rollout cwd.
    paths: Vec<PathBuf>,
}

#[derive(ClapArgs, Debug)]
struct OutputOptions {
    /// Number of rows to print. Use 0 for all rows.
    #[arg(long, default_value_t = 10)]
    limit: usize,

    /// Emit JSON instead of a text table.
    #[arg(long)]
    json: bool,

    /// Print only paths, one per line.
    #[arg(long, conflicts_with = "json")]
    paths_only: bool,

    /// Print rollout path and exec command count to stderr.
    #[arg(short, long)]
    verbose: bool,
}

#[derive(Debug, Default)]
struct Counts {
    files: BTreeMap<PathBuf, usize>,
    exec_calls: usize,
}

#[derive(Clone, Copy, Debug, Default)]
struct ScanRange {
    from_line: Option<usize>,
    to_line: Option<usize>,
    from_byte: Option<u64>,
    to_byte: Option<u64>,
}

impl ScanRange {
    fn lines(from: Option<usize>, to: Option<usize>) -> Result<Self> {
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

    fn bytes(from: u64, to: u64) -> Result<Self> {
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

#[derive(Debug, Default)]
struct Metadata {
    thread_id: Option<String>,
    cwd: Option<PathBuf>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Snapshot {
    format: String,
    thread_id: Option<String>,
    rollout: PathBuf,
    cwd: PathBuf,
    line: usize,
    byte_offset: u64,
}

#[derive(Debug, Serialize)]
struct FileCount {
    count: usize,
    path: String,
}

fn main() -> Result<()> {
    let cli = Cli::parse_from(args_with_default_subcommand());

    match cli.command {
        Command::Top(args) => run_top(args),
        Command::Snapshot(args) => run_snapshot(args),
        Command::Delta(args) => run_delta(args),
    }
}

fn args_with_default_subcommand() -> Vec<OsString> {
    let mut args: Vec<OsString> = env::args_os().collect();
    let Some(first) = args.get(1).and_then(|arg| arg.to_str()) else {
        return args;
    };

    let is_global_flag = matches!(first, "-h" | "--help" | "-V" | "--version");
    let is_subcommand = matches!(first, "top" | "snapshot" | "delta" | "help");
    if !is_global_flag && !is_subcommand && !first.starts_with('-') {
        args.insert(1, OsString::from("top"));
    }
    args
}

fn run_top(args: TopArgs) -> Result<()> {
    let rollout = resolve_rollout(&args.thread_or_rollout)?;
    let metadata = read_metadata(&rollout)?;
    let cwd = metadata
        .cwd
        .context("rollout cwd not found in session_meta")?;
    let filters = resolve_filters(&cwd, &args.paths);
    let range = ScanRange::lines(args.from_line, args.to_line)?;
    let counts = count_from_exec_calls(&rollout, &cwd, &filters, range)?;

    print_counts(&counts, &cwd, &rollout, &args.output)
}

fn run_snapshot(args: SnapshotArgs) -> Result<()> {
    let snapshot = create_snapshot(&args.thread_or_rollout)?;
    println!("{}", serde_json::to_string_pretty(&snapshot)?);
    Ok(())
}

fn run_delta(args: DeltaArgs) -> Result<()> {
    let from = read_snapshot_arg(&args.from)?;
    let to = match args.to.as_deref() {
        Some(path) => read_snapshot_arg(path)?,
        None => create_snapshot_from_rollout(&from.rollout)?,
    };
    validate_snapshot_pair(&from, &to)?;

    let filters = resolve_filters(&from.cwd, &args.paths);
    let range = ScanRange::bytes(from.byte_offset, to.byte_offset)?;
    let counts = count_from_exec_calls(&from.rollout, &from.cwd, &filters, range)?;

    print_delta(&counts, &from.cwd, &from, &to, &args.output)
}

fn create_snapshot(thread_or_rollout: &str) -> Result<Snapshot> {
    let rollout = resolve_rollout(thread_or_rollout)?;
    create_snapshot_from_rollout(&rollout)
}

fn create_snapshot_from_rollout(rollout: &Path) -> Result<Snapshot> {
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

fn validate_snapshot_pair(from: &Snapshot, to: &Snapshot) -> Result<()> {
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

fn read_snapshot_arg(path: &str) -> Result<Snapshot> {
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

fn read_metadata(rollout: &Path) -> Result<Metadata> {
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

fn parse_rollout_json_line(line: &str, line_no: usize) -> Result<Option<Value>> {
    match serde_json::from_str(line) {
        Ok(value) => Ok(Some(value)),
        Err(err) if !line.ends_with('\n') && err.is_eof() => Ok(None),
        Err(err) => Err(err).with_context(|| format!("parsing rollout JSON at line {line_no}")),
    }
}

#[derive(Debug)]
struct RolloutCursor {
    line: usize,
    byte_offset: u64,
}

fn rollout_cursor(rollout: &Path) -> Result<RolloutCursor> {
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
        line_count += 1;
        byte_offset += bytes as u64;
    }

    Ok(RolloutCursor {
        line: line_count,
        byte_offset,
    })
}

fn count_from_exec_calls(
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

fn print_counts(counts: &Counts, cwd: &Path, rollout: &Path, output: &OutputOptions) -> Result<()> {
    let rows = sorted_rows(counts, cwd, output.limit);
    if output.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "rollout": rollout,
                "exec_calls": counts.exec_calls,
                "files": rows,
            }))?
        );
        return Ok(());
    }

    print_verbose(counts, rollout, output);
    print_rows(&rows, output.paths_only);
    Ok(())
}

fn print_delta(
    counts: &Counts,
    cwd: &Path,
    from: &Snapshot,
    to: &Snapshot,
    output: &OutputOptions,
) -> Result<()> {
    let rows = sorted_rows(counts, cwd, output.limit);
    if output.json {
        println!(
            "{}",
            serde_json::to_string_pretty(&serde_json::json!({
                "from": from,
                "to": to,
                "exec_calls": counts.exec_calls,
                "files": rows,
            }))?
        );
        return Ok(());
    }

    print_verbose(counts, &from.rollout, output);
    print_rows(&rows, output.paths_only);
    Ok(())
}

fn print_verbose(counts: &Counts, rollout: &Path, output: &OutputOptions) {
    if output.verbose {
        eprintln!(
            "exec_calls={} rollout={}",
            counts.exec_calls,
            rollout.display()
        );
    }
}

fn sorted_rows(counts: &Counts, cwd: &Path, limit: usize) -> Vec<FileCount> {
    let mut rows: Vec<_> = counts.files.iter().collect();
    rows.sort_by(|(left_path, left_count), (right_path, right_count)| {
        right_count
            .cmp(left_count)
            .then_with(|| left_path.cmp(right_path))
    });
    if limit > 0 {
        rows.truncate(limit);
    }

    rows.into_iter()
        .map(|(path, count)| FileCount {
            count: *count,
            path: display_path(cwd, path),
        })
        .collect()
}

fn print_rows(rows: &[FileCount], paths_only: bool) {
    for row in rows {
        if paths_only {
            println!("{}", row.path);
        } else {
            println!("{:>5}  {}", row.count, row.path);
        }
    }
}

fn resolve_filters(cwd: &Path, paths: &[PathBuf]) -> Vec<PathBuf> {
    paths.iter().map(|path| resolve_path(cwd, path)).collect()
}

fn display_path(cwd: &Path, path: &Path) -> String {
    path.strip_prefix(cwd)
        .unwrap_or(path)
        .to_string_lossy()
        .into_owned()
}

fn resolve_rollout(value: &str) -> Result<PathBuf> {
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

fn resolve_path(cwd: &Path, path: &Path) -> PathBuf {
    let raw = if path.is_absolute() {
        path.to_path_buf()
    } else {
        cwd.join(path)
    };
    fs::canonicalize(&raw).unwrap_or_else(|_| normalize_path(&raw))
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            Component::Normal(part) => out.push(part),
            Component::RootDir | Component::Prefix(_) => out.push(component.as_os_str()),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn path_normalization_removes_dot_and_parent_segments() {
        assert_eq!(
            normalize_path(Path::new("/tmp/work/./a/../b")),
            PathBuf::from("/tmp/work/b")
        );
    }
}
