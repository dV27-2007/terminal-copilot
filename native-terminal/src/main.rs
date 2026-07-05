use terminal_copilot_native_terminal::app::{run, AppArgs};

fn main() {
    let args = AppArgs::parse(std::env::args().skip(1));
    run(args);
}
