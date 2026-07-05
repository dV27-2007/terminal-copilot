use super::TerminalState;

pub fn parse_bytes_into_state(bytes: &[u8], state: &mut TerminalState) {
    for ch in String::from_utf8_lossy(bytes).chars() {
        match ch {
            '\n' => state.newline(),
            '\r' => state.carriage_return(),
            '\u{8}' | '\u{7f}' => state.backspace(),
            ch if ch.is_control() => {}
            ch => state.insert_printable(ch),
        }
    }
}
