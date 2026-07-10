use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use serde_json::Value;
use tree_sitter::Node;
use tree_sitter::Parser;

pub(crate) fn exec_calls(source: &str) -> Result<Vec<Value>> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_javascript::LANGUAGE.into())
        .context("loading the JavaScript grammar")?;
    let tree = parser
        .parse(source, None)
        .context("parsing Codex exec tool input")?;
    if tree.root_node().has_error() {
        bail!("Codex exec tool input contains unsupported JavaScript syntax");
    }

    let mut calls = Vec::new();
    let mut direct_references = 0;
    let mut exec_command_tokens = 0;
    visit(
        tree.root_node(),
        source.as_bytes(),
        &mut calls,
        &mut direct_references,
        &mut exec_command_tokens,
    )?;
    if exec_command_tokens != direct_references || direct_references != calls.len() {
        bail!("tools.exec_command is referenced dynamically and cannot be audited");
    }
    Ok(calls)
}

fn visit(
    node: Node<'_>,
    source: &[u8],
    calls: &mut Vec<Value>,
    direct_references: &mut usize,
    exec_command_tokens: &mut usize,
) -> Result<()> {
    if matches!(
        node.kind(),
        "identifier" | "property_identifier" | "shorthand_property_identifier_pattern" | "string"
    ) && node_text(node, source)?.trim_matches(['\'', '"']) == "exec_command"
    {
        *exec_command_tokens += 1;
    }
    if node.kind() == "member_expression" && node_text(node, source)? == "tools.exec_command" {
        *direct_references += 1;
    }

    if node.kind() == "call_expression" {
        let function = node
            .child_by_field_name("function")
            .context("JavaScript call has no function")?;
        if node_text(function, source)? == "tools.exec_command" {
            let arguments = node
                .child_by_field_name("arguments")
                .context("tools.exec_command call has no arguments")?;
            if arguments.named_child_count() != 1 {
                bail!("tools.exec_command must have one static argument");
            }
            let argument = arguments
                .named_child(0)
                .context("tools.exec_command argument is missing")?;
            if argument.kind() != "object" {
                bail!("tools.exec_command argument is not a static object");
            }
            let value: Value = json5::from_str(node_text(argument, source)?)
                .context("tools.exec_command argument is not a static object")?;
            if !value.is_object() {
                bail!("tools.exec_command argument is not an object");
            }
            calls.push(value);
        }
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        visit(child, source, calls, direct_references, exec_command_tokens)?;
    }
    Ok(())
}

fn node_text<'a>(node: Node<'_>, source: &'a [u8]) -> Result<&'a str> {
    node.utf8_text(source)
        .context("Codex exec tool input is not valid UTF-8")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_static_exec_command_calls() -> Result<()> {
        let source = r#"
            const first = await tools.exec_command({
                cmd: "sed -n '1,20p' src/main.rs",
                workdir: "/workspace",
                login: false,
            });
            const second = await tools.exec_command({ cmd: "cat README.md" });
            text(first.output);
            text(second.output);
        "#;

        let calls = exec_calls(source)?;

        assert_eq!(calls.len(), 2);
        assert_eq!(calls[0]["cmd"], "sed -n '1,20p' src/main.rs");
        assert_eq!(calls[0]["workdir"], "/workspace");
        assert_eq!(calls[0]["login"], false);
        assert_eq!(calls[1]["cmd"], "cat README.md");
        Ok(())
    }

    #[test]
    fn ignores_other_nested_tools() -> Result<()> {
        let calls = exec_calls(
            r#"const result = await tools.apply_patch("*** Begin Patch"); text(result);"#,
        )?;
        assert!(calls.is_empty());
        Ok(())
    }

    #[test]
    fn rejects_dynamic_exec_arguments() {
        assert!(exec_calls("await tools.exec_command(options);").is_err());
        assert!(exec_calls("const run = tools.exec_command; await run(options);").is_err());
        assert!(exec_calls("const {exec_command} = tools; await exec_command(options);").is_err());
        assert!(exec_calls("await tools['exec_command'](options);").is_err());
    }
}
