use super::cell::Cell;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TerminalGrid {
    rows: usize,
    cols: usize,
    cells: Vec<Cell>,
}

impl TerminalGrid {
    pub fn new(rows: usize, cols: usize) -> Self {
        assert!(rows > 0, "terminal grid must have at least one row");
        assert!(cols > 0, "terminal grid must have at least one column");
        Self {
            rows,
            cols,
            cells: vec![Cell::blank(); rows * cols],
        }
    }

    pub fn rows(&self) -> usize {
        self.rows
    }

    pub fn cols(&self) -> usize {
        self.cols
    }

    pub fn get(&self, row: usize, col: usize) -> Option<&Cell> {
        if row >= self.rows || col >= self.cols {
            return None;
        }
        self.cells.get(self.index(row, col))
    }

    pub fn set(&mut self, row: usize, col: usize, cell: Cell) {
        if row >= self.rows || col >= self.cols {
            return;
        }
        let index = self.index(row, col);
        self.cells[index] = cell;
    }

    pub fn clear_row(&mut self, row: usize) {
        if row >= self.rows {
            return;
        }
        for col in 0..self.cols {
            self.set(row, col, Cell::blank());
        }
    }

    pub fn row_string(&self, row: usize) -> String {
        if row >= self.rows {
            return String::new();
        }
        let mut line = String::with_capacity(self.cols);
        for col in 0..self.cols {
            line.push(self.get(row, col).map(Cell::ch).unwrap_or(' '));
        }
        trim_trailing_spaces(line)
    }

    pub fn shift_up(&mut self) -> String {
        let scrolled = self.row_string(0);
        for row in 1..self.rows {
            for col in 0..self.cols {
                let cell = self.get(row, col).copied().unwrap_or_default();
                self.set(row - 1, col, cell);
            }
        }
        self.clear_row(self.rows - 1);
        scrolled
    }

    fn index(&self, row: usize, col: usize) -> usize {
        row * self.cols + col
    }
}

fn trim_trailing_spaces(mut line: String) -> String {
    while line.ends_with(' ') {
        line.pop();
    }
    line
}
