use anyhow::Result;
use clap::Args as ClapArgs;
use serde::Serialize;
use std::path::Path;

use crate::paths::canonical_path;
use crate::paths::display_path;
use crate::scanner::Counts;
use crate::snapshot::Snapshot;

#[derive(ClapArgs, Debug)]
pub(crate) struct OutputOptions {
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

#[derive(Debug, Serialize)]
struct FileCount {
    count: usize,
    path: String,
}

pub(crate) fn print_counts(
    counts: &Counts,
    cwd: &Path,
    rollout: &Path,
    output: &OutputOptions,
) -> Result<()> {
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

pub(crate) fn print_delta(
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
    let display_cwd = canonical_path(cwd);
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
            path: display_path(&display_cwd, path),
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::paths::resolve_path;
    use std::collections::BTreeMap;
    use std::env;
    use std::fs;
    use std::path::Path;
    use std::path::PathBuf;

    struct TempTestDir {
        path: PathBuf,
    }

    impl Drop for TempTestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    #[cfg(unix)]
    #[test]
    fn symlinked_cwd_displays_canonical_reads_as_relative_paths() -> Result<()> {
        use std::os::unix::fs::symlink;

        let root = TempTestDir {
            path: env::temp_dir().join(format!(
                "codex-readcov-output-symlink-{}",
                std::process::id()
            )),
        };
        let _ = fs::remove_dir_all(&root.path);
        let real_cwd = root.path.join("real");
        let linked_cwd = root.path.join("linked");
        fs::create_dir_all(real_cwd.join("src"))?;
        symlink(&real_cwd, &linked_cwd)?;

        let counts = Counts {
            files: BTreeMap::from([(resolve_path(&linked_cwd, Path::new("src/lib.rs")), 1)]),
            exec_calls: 1,
        };
        let rows = sorted_rows(&counts, &linked_cwd, 0);

        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].path, "src/lib.rs");

        Ok(())
    }
}
