const std = @import("std");
const cli = @import("cli.zig");
const result = @import("result.zig");
const process = @import("process.zig");
const backend = @import("backend.zig");

fn writeAll(fd: std.posix.fd_t, bytes: []const u8, cancellable: bool) !void {
    const flags = try std.posix.fcntl(fd, std.posix.F.GETFL, 0);
    _ = try std.posix.fcntl(fd, std.posix.F.SETFL, flags | @as(u32, @bitCast(std.posix.O{ .NONBLOCK = true })));
    defer _ = std.posix.fcntl(fd, std.posix.F.SETFL, flags) catch 0;
    var deadline = try process.Deadline.init(2);
    var offset: usize = 0;
    while (offset < bytes.len and !deadline.expired()) {
        if (cancellable) try process.checkCancellation();
        const n = std.posix.write(fd, bytes[offset..]) catch |err| switch (err) {
            error.WouldBlock => {
                var fds = [_]std.posix.pollfd{.{ .fd = fd, .events = std.posix.POLL.OUT, .revents = 0 }};
                _ = try std.posix.poll(&fds, 20);
                continue;
            },
            else => return err,
        };
        if (n == 0) return error.OutputClosed;
        offset += n;
    }
    if (cancellable) try process.checkCancellation();
    if (offset != bytes.len) return error.OutputClosed;
}

fn outputFailure(err: anyerror) noreturn {
    std.process.exit(switch (err) {
        error.Interrupted => 130,
        error.Terminated => 143,
        else => 1,
    });
}

fn writeResult(fd: std.posix.fd_t, bytes: []const u8, exit_code: u8) void {
    // An already-cancelled run still gets its one bounded result. A new
    // cancellation during other output stops delivery without a second envelope.
    writeAll(fd, bytes, exit_code != 130 and exit_code != 143) catch |err| outputFailure(err);
}

fn emit(allocator: std.mem.Allocator, value: result.Result, json: bool, exit_code: u8) noreturn {
    if (json) {
        const bytes = std.json.Stringify.valueAlloc(allocator, value, .{}) catch std.process.exit(1);
        writeResult(std.posix.STDOUT_FILENO, bytes, exit_code);
        writeResult(std.posix.STDOUT_FILENO, "\n", exit_code);
    } else if (value.@"error") |err| {
        writeResult(std.posix.STDERR_FILENO, err.code, exit_code);
        writeResult(std.posix.STDERR_FILENO, ": ", exit_code);
        writeResult(std.posix.STDERR_FILENO, err.message, exit_code);
        writeResult(std.posix.STDERR_FILENO, "\n", exit_code);
    } else {
        writeResult(std.posix.STDOUT_FILENO, value.summary, exit_code);
        writeResult(std.posix.STDOUT_FILENO, "\n", exit_code);
    }
    std.process.exit(exit_code);
}

pub fn main() void {
    std.posix.sigaction(std.posix.SIG.PIPE, &.{ .handler = .{ .handler = std.posix.SIG.IGN }, .mask = std.posix.sigemptyset(), .flags = 0 }, null);
    process.installSignals();
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    var timer = std.time.Timer.start() catch null;
    const argv = std.process.argsAlloc(allocator) catch std.process.exit(1);
    const args = argv[1..];
    const json = cli.wantsJson(args);
    // Only this environment key configures zigagent. Help/version ignore it.
    const env_model = std.process.getEnvVarOwned(allocator, "ZIGAGENT_MODEL") catch null;
    const opts = cli.parse(allocator, args, env_model) catch {
        emit(allocator, .{ .@"error" = .{ .code = "usage_error", .message = "Invalid arguments; use zigagent --help or zigagent run --help." } }, json, 2);
    };
    const text: ?[]const u8 = switch (opts.command) {
        .help => cli.help,
        .run_help => cli.run_help,
        .login_help => cli.login_help,
        .version => "zigagent " ++ cli.version ++ "\n",
        else => null,
    };
    if (text) |bytes| {
        writeAll(std.posix.STDOUT_FILENO, bytes, true) catch |err| outputFailure(err);
        return;
    }
    var value: result.Result = .{};
    value.backend.model = opts.model;
    value.verification.status = if (opts.check != null) .not_run else .not_requested;
    cli.validatePaths(opts) catch {
        value.@"error" = .{ .code = "usage_error", .message = "Workspace and additional context paths must be accessible directories." };
        emit(allocator, value, json, 2);
    };
    const exit_code = backend.run(allocator, opts, &value) catch |err| blk: {
        switch (err) {
            error.Interrupted, error.Terminated => {
                value.status = .cancelled;
                value.@"error" = .{ .code = "cancelled", .message = "Cancelled; edits are preserved." };
                break :blk @as(u8, if (err == error.Interrupted) 130 else 143);
            },
            error.OutputClosed => std.process.exit(1),
            else => {},
        }
        value.@"error" = .{ .code = "backend_failed", .message = "Backend supervision failed; edits are preserved." };
        break :blk @as(u8, 1);
    };
    value.elapsed_ms = if (timer) |*t| t.read() / std.time.ns_per_ms else 0;
    emit(allocator, value, opts.json, exit_code);
}

test {
    _ = @import("cli.zig");
    _ = @import("result.zig");
    _ = @import("stream.zig");
}
