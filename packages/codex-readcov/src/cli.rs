use anyhow::Context;
use anyhow::Result;
use clap::Args as ClapArgs;
use clap::Parser;
use clap::Subcommand;
use std::env;
use std::ffi::OsString;
use std::path::PathBuf;

use crate::output;
use crate::output::OutputOptions;
use crate::paths::resolve_filters;
use crate::rollout::read_metadata;
use crate::rollout::resolve_rollout;
use crate::scanner::ScanRange;
use crate::scanner::count_from_exec_calls;
use crate::snapshot::create_snapshot;
use crate::snapshot::create_snapshot_from_rollout;
use crate::snapshot::read_snapshot_arg;
use crate::snapshot::validate_snapshot_pair;

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

pub(crate) fn run() -> Result<()> {
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

    output::print_counts(&counts, &cwd, &rollout, &args.output)
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

    output::print_delta(&counts, &from.cwd, &from, &to, &args.output)
}
