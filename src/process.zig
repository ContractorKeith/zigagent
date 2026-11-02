const std = @import("std");
const stream = @import("stream.zig");
const posix = std.posix;

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
        var fds = [_]posix.pollfd{.{ .fd = 0, .events = posix.POLL.IN, .revents = 0 }};
        _ = try posix.poll(&fds, 20);
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
    timed_out: bool = false,
    exit_zero: bool = false,
    input_incomplete: bool = false,

    pub fn init(a: std.mem.Allocator, output_limit: usize) !Capture {
        return .{
            .output = try stream.Buffer.init(a, 4096),
            .probe_stderr = try stream.Buffer.init(a, 4096),
            .diagnostics = try stream.Buffer.init(a, output_limit),
        };
    }
};

// A dedicated group and nonblocking pipes bound every workload, including probes.
// Keep the leader unreaped while draining inherited pipes so its group id cannot
// be recycled before deadline cleanup. M2 adds graceful cancellation handling.
pub fn run(a: std.mem.Allocator, argv: []const []const u8, input: ?[]const u8, deadline: *Deadline, capture: *Capture) !void {
    if (deadline.expired()) {
        capture.timed_out = true;
        return;
    }
    var child = std.process.Child.init(argv, a);
    child.pgid = 0;
    child.stdin_behavior = if (input != null) .Pipe else .Ignore;
    child.stdout_behavior = .Pipe;
    child.stderr_behavior = .Pipe;
    // Prevent API-key environment overrides from changing the checked login mode.
    var env = try std.process.getEnvMap(a);
    defer env.deinit();
    env.remove("CODEX_API_KEY");
    env.remove("OPENAI_API_KEY");
    child.env_map = &env;
    try child.spawn();
    var reaped = false;
    var cleanup: ?Deadline = null;
    defer {
        if (!reaped) {
            stop(child.id);
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
        if (cleanup == null and deadline.expired()) {
            capture.timed_out = true;
            stop(child.id);
            cleanup = try Deadline.init(2);
        }
        if (cleanup) |*d| {
            if (d.expired()) return; // Preserve the timeout result even if the OS cannot reap.
        }
        if (child.stdout == null and child.stderr == null or cleanup != null) {
            const waited = posix.waitpid(child.id, posix.W.NOHANG);
            if (waited.pid != 0) {
                reaped = true;
                capture.exit_zero = posix.W.IFEXITED(waited.status) and posix.W.EXITSTATUS(waited.status) == 0;
                // After exit the exec-error pipe is guaranteed closed or contains errno.
                try child.waitForSpawn();
                break;
            }
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
                    child.stdout.?.close();
                    child.stdout = null;
                } else {
                    child.stderr.?.close();
                    child.stderr = null;
                }
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
    capture.input_incomplete = if (input) |data| written != data.len else false;
    if (capture.events) |events| events.finish();
}

// The unreaped leader pins both identifiers; also stop it if deadline/error
// cleanup races the child's setpgid before exec.
fn stop(pid: posix.pid_t) void {
    posix.kill(-pid, posix.SIG.KILL) catch {};
    posix.kill(pid, posix.SIG.KILL) catch {};
}
