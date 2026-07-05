#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Scrollback {
    max_lines: usize,
    lines: Vec<String>,
}

impl Scrollback {
    pub fn new(max_lines: usize) -> Self {
        Self {
            max_lines,
            lines: Vec::new(),
        }
    }

    pub fn push(&mut self, line: String) {
        if self.max_lines == 0 {
            return;
        }
        self.lines.push(line);
        if self.lines.len() > self.max_lines {
            let excess = self.lines.len() - self.max_lines;
            self.lines.drain(0..excess);
        }
    }

    pub fn len(&self) -> usize {
        self.lines.len()
    }

    pub fn is_empty(&self) -> bool {
        self.lines.is_empty()
    }

    pub fn lines(&self) -> &[String] {
        &self.lines
    }
}

impl Default for Scrollback {
    fn default() -> Self {
        Self::new(10_000)
    }
}
