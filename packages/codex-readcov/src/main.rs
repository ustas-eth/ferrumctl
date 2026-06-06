mod cli;
mod output;
mod paths;
mod rollout;
mod scanner;
mod snapshot;

use anyhow::Result;

fn main() -> Result<()> {
    cli::run()
}
