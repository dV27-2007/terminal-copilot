#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cell {
    ch: char,
}

impl Cell {
    pub fn new(ch: char) -> Self {
        Self { ch }
    }

    pub fn blank() -> Self {
        Self { ch: ' ' }
    }

    pub fn ch(&self) -> char {
        self.ch
    }

    pub fn is_blank(&self) -> bool {
        self.ch == ' '
    }
}

impl Default for Cell {
    fn default() -> Self {
        Self::blank()
    }
}
