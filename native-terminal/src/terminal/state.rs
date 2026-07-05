use super::{Cell, Cursor, Scrollback, TerminalGrid};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TerminalState {
    grid: TerminalGrid,
    cursor: Cursor,
    scrollback: Scrollback,
}

impl TerminalState {
    pub fn new(rows: usize, cols: usize) -> Self {
        Self {
            grid: TerminalGrid::new(rows, cols),
            cursor: Cursor::default(),
            scrollback: Scrollback::default(),
        }
    }

    pub fn grid(&self) -> &TerminalGrid {
        &self.grid
    }

    pub fn cursor(&self) -> Cursor {
        self.cursor
    }

    pub fn scrollback(&self) -> &Scrollback {
        &self.scrollback
    }

    pub fn insert_printable(&mut self, ch: char) {
        if ch.is_control() {
            return;
        }
        self.grid
            .set(self.cursor.row, self.cursor.col, Cell::new(ch));
        self.advance_cursor();
    }

    pub fn newline(&mut self) {
        self.cursor.col = 0;
        self.cursor.row += 1;
        self.scroll_if_needed();
    }

    pub fn carriage_return(&mut self) {
        self.cursor.col = 0;
    }

    pub fn backspace(&mut self) {
        if self.cursor.col > 0 {
            self.cursor.col -= 1;
        }
    }

    pub fn visible_lines(&self) -> Vec<String> {
        (0..self.grid.rows())
            .map(|row| self.grid.row_string(row))
            .collect()
    }

    fn advance_cursor(&mut self) {
        self.cursor.col += 1;
        if self.cursor.col >= self.grid.cols() {
            self.cursor.col = 0;
            self.cursor.row += 1;
            self.scroll_if_needed();
        }
    }

    fn scroll_if_needed(&mut self) {
        while self.cursor.row >= self.grid.rows() {
            let scrolled = self.grid.shift_up();
            self.scrollback.push(scrolled);
            self.cursor.row = self.grid.rows() - 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::TerminalState;
    use crate::terminal::parse_bytes_into_state;

    #[test]
    fn empty_grid_initializes_with_expected_size() {
        let state = TerminalState::new(3, 5);

        assert_eq!(state.grid().rows(), 3);
        assert_eq!(state.grid().cols(), 5);
        assert_eq!(state.visible_lines(), vec!["", "", ""]);
        assert_eq!(state.cursor().row, 0);
        assert_eq!(state.cursor().col, 0);
    }

    #[test]
    fn printable_characters_appear_in_cells() {
        let mut state = TerminalState::new(2, 4);

        parse_bytes_into_state(b"ab", &mut state);

        assert_eq!(state.grid().get(0, 0).unwrap().ch(), 'a');
        assert_eq!(state.grid().get(0, 1).unwrap().ch(), 'b');
        assert_eq!(state.visible_lines()[0], "ab");
    }

    #[test]
    fn cursor_advances_after_printable_input() {
        let mut state = TerminalState::new(2, 4);

        parse_bytes_into_state(b"ab", &mut state);

        assert_eq!(state.cursor().row, 0);
        assert_eq!(state.cursor().col, 2);
    }

    #[test]
    fn newline_moves_to_next_row() {
        let mut state = TerminalState::new(3, 4);

        parse_bytes_into_state(b"a\nb", &mut state);

        assert_eq!(state.visible_lines(), vec!["a", "b", ""]);
        assert_eq!(state.cursor().row, 1);
        assert_eq!(state.cursor().col, 1);
    }

    #[test]
    fn carriage_return_moves_to_column_zero() {
        let mut state = TerminalState::new(2, 4);

        parse_bytes_into_state(b"ab\rc", &mut state);

        assert_eq!(state.visible_lines()[0], "cb");
        assert_eq!(state.cursor().row, 0);
        assert_eq!(state.cursor().col, 1);
    }

    #[test]
    fn backspace_moves_cursor_back_safely() {
        let mut state = TerminalState::new(2, 4);

        parse_bytes_into_state(b"ab\x08c", &mut state);
        state.backspace();
        state.backspace();
        state.backspace();

        assert_eq!(state.visible_lines()[0], "ac");
        assert_eq!(state.cursor().row, 0);
        assert_eq!(state.cursor().col, 0);
    }

    #[test]
    fn scroll_occurs_after_bottom_row() {
        let mut state = TerminalState::new(2, 4);

        parse_bytes_into_state(b"one\ntwo\nthr", &mut state);

        assert_eq!(state.scrollback().len(), 1);
        assert_eq!(state.scrollback().lines()[0], "one");
        assert_eq!(state.visible_lines(), vec!["two", "thr"]);
    }

    #[test]
    fn long_line_behavior_is_deterministic() {
        let mut state = TerminalState::new(2, 4);

        parse_bytes_into_state(b"abcdefghi", &mut state);

        assert_eq!(
            state.scrollback().lines(),
            [String::from("abcd")].as_slice()
        );
        assert_eq!(state.visible_lines(), vec!["efgh", "i"]);
        assert_eq!(state.cursor().row, 1);
        assert_eq!(state.cursor().col, 1);
    }

    #[test]
    fn visible_lines_can_be_extracted_as_strings() {
        let mut state = TerminalState::new(3, 6);

        parse_bytes_into_state(b"hi\nthere", &mut state);

        assert_eq!(state.visible_lines(), vec!["hi", "there", ""]);
    }

    #[test]
    fn empty_input_does_not_panic() {
        let mut state = TerminalState::new(2, 2);

        parse_bytes_into_state(b"", &mut state);

        assert_eq!(state.visible_lines(), vec!["", ""]);
        assert_eq!(state.cursor().row, 0);
        assert_eq!(state.cursor().col, 0);
    }
}
