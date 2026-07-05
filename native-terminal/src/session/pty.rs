#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PtySessionConfig {
    pub shell: String,
    pub rows: usize,
    pub cols: usize,
}

impl PtySessionConfig {
    pub fn new(shell: impl Into<String>, rows: usize, cols: usize) -> Self {
        Self {
            shell: shell.into(),
            rows,
            cols,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PtySession {
    config: PtySessionConfig,
}

impl PtySession {
    pub fn placeholder(config: PtySessionConfig) -> Self {
        Self { config }
    }

    pub fn config(&self) -> &PtySessionConfig {
        &self.config
    }

    pub fn is_real_pty(&self) -> bool {
        false
    }

    pub fn status(&self) -> &'static str {
        "real PTY shell sessions are deferred to Stage 18"
    }
}
