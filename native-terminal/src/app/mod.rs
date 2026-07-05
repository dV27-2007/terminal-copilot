use crate::terminal::{parse_bytes_into_state, TerminalState};

const VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AppArgs {
    Version,
    HeadlessDemo,
    Help,
    Normal,
}

impl AppArgs {
    pub fn parse<I>(args: I) -> Self
    where
        I: IntoIterator<Item = String>,
    {
        let mut parsed = AppArgs::Normal;
        for arg in args {
            parsed = match arg.as_str() {
                "--version" | "-V" => AppArgs::Version,
                "--headless-demo" => AppArgs::HeadlessDemo,
                "--help" | "-h" => AppArgs::Help,
                _ => AppArgs::Normal,
            };
            if parsed != AppArgs::Normal {
                break;
            }
        }
        parsed
    }
}

pub fn run(args: AppArgs) {
    match args {
        AppArgs::Version => println!("native-terminal {}", VERSION),
        AppArgs::HeadlessDemo => run_headless_demo(),
        AppArgs::Help => print_help(),
        AppArgs::Normal => {
            println!("native terminal renderer is not implemented yet; use --headless-demo for core demo")
        }
    }
}

fn run_headless_demo() {
    let mut state = TerminalState::new(4, 20);
    parse_bytes_into_state(
        b"terminal-copilot\nnative core demo\nlong line wraps deterministically",
        &mut state,
    );

    println!("native terminal headless demo");
    for line in state.visible_lines() {
        println!("{line}");
    }
}

fn print_help() {
    println!("native-terminal");
    println!("  --version        print version");
    println!("  --headless-demo  run terminal core demo without a GUI");
}
