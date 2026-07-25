use std::ffi::OsString;
use std::fs;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

pub(crate) fn resolve_filters(cwd: &Path, paths: &[PathBuf]) -> Vec<PathBuf> {
    paths.iter().map(|path| resolve_path(cwd, path)).collect()
}

pub(crate) fn display_path(cwd: &Path, path: &Path) -> String {
    path.strip_prefix(cwd)
        .unwrap_or(path)
        .to_string_lossy()
        .into_owned()
}

pub(crate) fn canonical_path(path: &Path) -> PathBuf {
    if let Ok(path) = fs::canonicalize(path) {
        return path;
    }

    let normalized = normalize_path(path);
    let mut ancestor = path;
    let mut suffix: Vec<OsString> = Vec::new();
    loop {
        if let Ok(mut resolved) = fs::canonicalize(ancestor) {
            for component in suffix.iter().rev() {
                resolved.push(component);
            }
            return normalize_path(&resolved);
        }

        let Some(component) = ancestor.file_name() else {
            return normalized;
        };
        let Some(parent) = ancestor.parent() else {
            return normalized;
        };
        suffix.push(component.to_os_string());
        ancestor = parent;
    }
}

pub(crate) fn resolve_path(cwd: &Path, path: &Path) -> PathBuf {
    let raw = if path.is_absolute() {
        path.to_path_buf()
    } else {
        cwd.join(path)
    };
    canonical_path(&raw)
}

pub(crate) fn normalize_path(path: &Path) -> PathBuf {
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
    use std::env;

    struct TempTestDir {
        path: PathBuf,
    }

    impl Drop for TempTestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.path);
        }
    }

    #[test]
    fn path_normalization_removes_dot_and_parent_segments() {
        assert_eq!(
            normalize_path(Path::new("/tmp/work/./a/../b")),
            PathBuf::from("/tmp/work/b")
        );
    }

    #[cfg(unix)]
    #[test]
    fn missing_descendants_resolve_through_intermediate_symlinks() {
        use std::os::unix::fs::symlink;

        let root = TempTestDir {
            path: env::temp_dir()
                .join(format!("codex-readcov-path-symlink-{}", std::process::id())),
        };
        let _ = fs::remove_dir_all(&root.path);
        let real = root.path.join("nested/real");
        let linked = root.path.join("linked");
        fs::create_dir_all(&real).expect("create real directory");
        symlink(&real, &linked).expect("create symlink");

        let relative = resolve_path(&root.path, Path::new("linked/generated/out.rs"));
        let absolute = resolve_path(&root.path, &linked.join("generated/out.rs"));
        let parent = resolve_path(&root.path, Path::new("linked/../pending.rs"));
        let expected = real.join("generated/out.rs");

        assert_eq!(relative, expected);
        assert_eq!(absolute, expected);
        assert_eq!(parent, root.path.join("nested/pending.rs"));
    }
}
