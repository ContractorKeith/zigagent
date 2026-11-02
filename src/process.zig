const std = @import("std");
const stream = @import("stream.zig");
const posix = std.posix;
const c = @cImport({
    @cInclude("sys/wait.h");
    @cInclude("signal.h");
    @cInclude("unistd.h");
    @cInclude("fcntl.h");
});

var cancellation = std.atomic.Value(u8).init(0);
fn onSignal(sig: i32) callconv(.c) void {
    cancellation.store(@intCast(sig), .monotonic);
}
pub fn installSignals() void {
    for ([_]u6{ posix.SIG.INT, posix.SIG.TERM }) |sig|
        posix.sigaction(sig, &.{ .handler = .{ .handler = onSignal }, .mask = posix.sigemptyset(), .flags = 0 }, null);
    posix.sigaction(posix.SIG.TTOU, &.{ .handler = .{ .handler = posix.SIG.IGN }, .mask = posix.sigemptyset(), .flags = 0 }, null);
}
pub fn checkCancellation() !void {
    switch (cancellation.load(.monotonic)) {
        posix.SIG.INT => return error.Interrupted,
        posix.SIG.TERM => return error.Terminated,
        else => {},
    }
}
pub fn checkCaller() !void {
    try checkCancellation();
    // Darwin registers no kqueue filter for an empty event mask.
    var fds = [_]posix.pollfd{.{ .fd = 1, .events = posix.POLL.OUT, .revents = 0 }};
    _ = try posix.poll(&fds, 0);
    if (fds[0].revents & (posix.POLL.ERR | posix.POLL.HUP | posix.POLL.NVAL) != 0) return error.OutputClosed;
}

// ENXIO is the normal no-controlling-terminal case. std.posix.open treats
// it as unexpected and prints a debug trace, so handle this OS boundary here.
pub fn openTerminal(output_only: bool) !posix.fd_t {
    const flags: c_int = c.O_CLOEXEC | (if (output_only) c.O_WRONLY | c.O_NONBLOCK else c.O_RDWR);
    const fd = c.open("/dev/tty", flags);
    if (fd < 0) return error.NoTerminal;
    // Never occupy a closed standard descriptor or leave CLOEXEC on login stdin.
    if (fd < 3) {
        const moved = c.fcntl(fd, c.F_DUPFD_CLOEXEC, @as(c_int, 3));
        posix.close(fd);
        if (moved < 0) return error.NoTerminal;
        return moved;
    }
    return fd;
}

pub const Deadline = struct {
    timer: std.time.Timer,
    limit: u64,
    pub fn init(seconds: u32) !Deadline {
        return .{ .timer = try std.time.Timer.start(), .limit = @as(u64, seconds) * std.time.ns_per_s };
    }
    pub fn expired(self: *Deadline) bool {
        return self.timer.read() >= self.limit;
    }
};

pub fn readPrompt(a: std.mem.Allocator, limit: usize, deadline: *Deadline) ![]const u8 {
    if (posix.isatty(posix.STDIN_FILENO)) return error.Usage;
    var buffer = try stream.Buffer.init(a, limit);
    var chunk: [8192]u8 = undefined;
    while (!deadline.expired()) {
        try checkCaller();
        var fds = [_]posix.pollfd{.{ .fd = 0, .events = posix.POLL.IN, .revents = 0 }};
        _ = try posix.poll(&fds, 20);
        try checkCaller();
        if (fds[0].revents == 0) continue;
        const n = try posix.read(0, &chunk);
        if (n == 0) {
            if (buffer.len == 0 or !std.unicode.utf8ValidateSlice(buffer.slice()) or std.mem.indexOfScalar(u8, buffer.slice(), 0) != null) return error.Usage;
            return buffer.slice();
        }
        buffer.prefix(chunk[0..n]);
        if (buffer.truncated) return error.Usage;
    }
    return error.TimedOut;
}

fn nonblocking(fd: posix.fd_t) !void {
    const flags = try posix.fcntl(fd, posix.F.GETFL, 0);
    _ = try posix.fcntl(fd, posix.F.SETFL, flags | @as(u32, @bitCast(posix.O{ .NONBLOCK = true })));
}

pub const Capture = struct {
    output: stream.Buffer,
    diagnostics: stream.Buffer,
    // Auth/version recognition is independent of the caller's diagnostic limit.
    probe_stderr: stream.Buffer,
    events: ?*stream.Events = null,
    cwd_dir: ?std.fs.Dir = null,
    combined_output: bool = false,
    codex_environment: bool = true,
    started: bool = false,
    terminal: ?posix.fd_t = null,
    terminal_output: ?posix.fd_t = null,
    timed_out: bool = false,
    exit_zero: bool = false,
    input_incomplete: bool = false,
    cleanup_incomplete: bool = false,
    exit_signal: ?u8 = null,
    exit_code: ?u8 = null,

    pub fn init(a: std.mem.Allocator, output_limit: usize) !Capture {
        return .{
            .output = try stream.Buffer.init(a, 4096),
            .probe_stderr = try stream.Buffer.init(a, 4096),
            .diagnostics = try stream.Buffer.init(a, output_limit),
        };
    }
};

// A dedicated group and nonblocking pipes bound every workload, including probes.
// Observe exit with WNOWAIT: the unreaped leader pins its PID/group until
// the final group signal, including descendants that closed inherited pipes.
pub fn run(a: std.mem.Allocator, argv: []const []const u8, input: ?[]const u8, deadline: *Deadline, capture: *Capture) !void {
    try checkCaller();
    if (deadline.expired()) {
        capture.timed_out = true;
        return;
    }
    // Zig Child's pipe setup assumes standard slots are occupied. Otherwise a
    // CLOEXEC pipe may become fd 0 and survive dup2(0, 0) with CLOEXEC still set.
    const stdin_flags = c.fcntl(0, c.F_GETFD);
    const missing_stdin = stdin_flags < 0 and posix.errno(stdin_flags) == .BADF;
    if (stdin_flags < 0 and !missing_stdin) return error.DupFailed;
    if (missing_stdin and c.open("/dev/null", c.O_RDONLY | c.O_CLOEXEC) < 0) return error.DupFailed;
    defer if (missing_stdin) posix.close(0);
    var child = std.process.Child.init(argv, a);
    child.pgid = 0;
    child.cwd_dir = capture.cwd_dir;
    child.stdin_behavior = if (capture.terminal != null) .Inherit else if (input != null) .Pipe else .Ignore;
    child.stdout_behavior = .Pipe;
    child.stderr_behavior = .Pipe;
    // Prevent API-key environment overrides from changing the checked login mode.
    var env = try std.process.getEnvMap(a);
    defer env.deinit();
    if (capture.codex_environment) {
        env.remove("CODEX_API_KEY");
        env.remove("OPENAI_API_KEY");
    }
    child.env_map = &env;
    // Environment/setup time also consumes the shared deadline.
    try checkCaller();
    if (deadline.expired()) {
        capture.timed_out = true;
        return;
    }
    // Child has no arbitrary-fd stdin option. Restore caller stdin immediately
    // after spawn; only official login inherits the controlling terminal.
    if (capture.terminal) |tty| {
        const saved = c.fcntl(0, c.F_DUPFD_CLOEXEC, @as(c_int, 3));
        if (saved < 0 and posix.errno(saved) != .BADF) return error.DupFailed;
        defer if (saved >= 0) posix.close(saved);
        try posix.dup2(tty, 0);
        defer {
            if (saved >= 0) posix.dup2(saved, 0) catch {} else posix.close(0);
        }
        try child.spawn();
    } else try child.spawn();
    capture.started = true;
    const foreground = if (capture.terminal) |tty| c.tcgetpgrp(tty) else -1;
    if (capture.terminal) |tty| {
        // Both sides establish the same group, closing the fork/setpgid race.
        _ = c.setpgid(child.id, child.id);
        _ = c.tcsetpgrp(tty, child.id);
        posix.kill(-child.id, posix.SIG.CONT) catch {};
    }
    defer if (capture.terminal) |tty| {
        _ = c.tcsetpgrp(tty, foreground);
    };
    var reaped = false;
    var cleanup: ?Deadline = null;
    var stop_error: ?anyerror = null;
    var leader_exited = false;
    var killed = false;
    defer {
        if (!reaped) {
            signalGroup(child.id, posix.SIG.KILL);
            // Error paths must also reap without an unbounded Child.wait().
            var cleanup_deadline = cleanup orelse (Deadline.init(2) catch unreachable);
            while (!cleanup_deadline.expired()) {
                if (posix.waitpid(child.id, posix.W.NOHANG).pid != 0) break;
                _ = posix.poll(&.{}, 20) catch 0;
            }
        }
        if (child.stdin) |f| f.close();
        if (child.stdout) |f| f.close();
        if (child.stderr) |f| f.close();
        if (child.err_pipe) |fd| posix.close(fd);
    }
    try nonblocking(child.stdout.?.handle);
    try nonblocking(child.stderr.?.handle);
    if (child.stdin) |f| try nonblocking(f.handle);
    var written: usize = 0;
    var chunk: [8192]u8 = undefined;
    while (true) {
        checkCaller() catch |err| {
            if (stop_error == null) stop_error = err;
        };
        if (cleanup == null) {
            if (deadline.expired()) capture.timed_out = true;
            var info: c.siginfo_t = std.mem.zeroes(c.siginfo_t);
            const rc = c.waitid(c.P_PID, @intCast(child.id), &info, c.WEXITED | c.WNOHANG | c.WNOWAIT);
            if (rc != 0) {
                if (posix.errno(rc) == .INTR) continue;
                return error.WaitFailed;
            }
            leader_exited = info.si_signo != 0;
            const invalid_event = if (capture.events) |events| events.too_large or events.protocol_error else false;
            if (leader_exited or capture.timed_out or stop_error != null or invalid_event) {
                signalGroup(child.id, posix.SIG.TERM);
                cleanup = try Deadline.init(3);
            }
        }
        if (cleanup) |*d| {
            // Normal exit gets 100ms for ordinary descendants; cancellation and
            // deadlines get one second. Never reap before the final group kill.
            const grace: u64 = if (leader_exited and stop_error == null and !capture.timed_out) 100 * std.time.ns_per_ms else std.time.ns_per_s;
            if (!killed and d.timer.read() >= grace) {
                signalGroup(child.id, posix.SIG.KILL);
                killed = true;
            }
            if (killed and !reaped) {
                const waited = posix.waitpid(child.id, posix.W.NOHANG);
                if (waited.pid != 0) {
                    reaped = true;
                    capture.exit_zero = posix.W.IFEXITED(waited.status) and posix.W.EXITSTATUS(waited.status) == 0;
                    if (posix.W.IFEXITED(waited.status)) capture.exit_code = @intCast(posix.W.EXITSTATUS(waited.status));
                    if (posix.W.IFSIGNALED(waited.status)) capture.exit_signal = @intCast(posix.W.TERMSIG(waited.status));
                    try child.waitForSpawn();
                    // Drain already buffered bytes below, but never wait on an
                    // escaped pipe holder beyond this finite cleanup budget.
                }
            }
            if (d.expired()) {
                capture.cleanup_incomplete = true;
                capture.exit_zero = false;
                break;
            }
            if (reaped and child.stdout == null and child.stderr == null) break;
        }
        var fds = [_]posix.pollfd{
            .{ .fd = if (child.stdout) |f| f.handle else -1, .events = posix.POLL.IN, .revents = 0 },
            .{ .fd = if (child.stderr) |f| f.handle else -1, .events = posix.POLL.IN, .revents = 0 },
            .{ .fd = if (child.stdin) |f| f.handle else -1, .events = posix.POLL.OUT, .revents = 0 },
        };
        _ = try posix.poll(&fds, 20);
        for (fds[0..2], 0..) |fd, i| {
            if (fd.fd < 0 or fd.revents == 0) continue;
            const n = posix.read(fd.fd, &chunk) catch |err| switch (err) {
                error.WouldBlock => continue,
                else => return err,
            };
            if (n == 0) {
                if (i == 0) {
                    if (capture.events) |events| events.finish();
                    child.stdout.?.close();
                    child.stdout = null;
                } else {
                    child.stderr.?.close();
                    child.stderr = null;
                }
            } else if (capture.terminal_output) |tty| {
                _ = posix.write(tty, chunk[0..n]) catch 0;
            } else if (capture.combined_output) {
                capture.diagnostics.tail(chunk[0..n]);
            } else if (i == 0) {
                if (capture.events) |events| events.feed(chunk[0..n]) else capture.output.prefix(chunk[0..n]);
            } else {
                capture.diagnostics.tail(chunk[0..n]);
                if (capture.events == null) capture.probe_stderr.prefix(chunk[0..n]);
            }
        }
        if (child.stdin != null and fds[2].revents != 0) {
            const data = input.?;
            const n = posix.write(fds[2].fd, data[written..@min(data.len, written + 8192)]) catch |err| switch (err) {
                error.WouldBlock => continue,
                error.BrokenPipe => 0,
                else => return err,
            };
            written += n;
            if (written == data.len or n == 0) {
                child.stdin.?.close();
                child.stdin = null;
            }
        }
    }
    if (stop_error) |err| return err;
    capture.input_incomplete = if (input) |data| written != data.len else false;
    if (capture.events) |events| events.finish();
}

// The unreaped leader pins both identifiers; also stop it if deadline/error
// cleanup races the child's setpgid before exec.
fn signalGroup(pid: posix.pid_t, sig: u8) void {
    posix.kill(-pid, sig) catch {};
    posix.kill(pid, sig) catch {};
}
