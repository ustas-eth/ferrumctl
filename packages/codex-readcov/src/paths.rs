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

pub(crate) fn resolve_path(cwd: &Path, path: &Path) -> PathBuf {
    let raw = if path.is_absolute() {
        path.to_path_buf()
    } else {
        cwd.join(path)
    };
    fs::canonicalize(&raw).unwrap_or_else(|_| normalize_path(&raw))
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

    #[test]
    fn path_normalization_removes_dot_and_parent_segments() {
        assert_eq!(
            normalize_path(Path::new("/tmp/work/./a/../b")),
            PathBuf::from("/tmp/work/b")
        );
    }
}
