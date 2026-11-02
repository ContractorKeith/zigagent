const std = @import("std");
const cli = @import("cli.zig");
const result = @import("result.zig");

fn writeAll(fd: std.posix.fd_t, bytes: []const u8) !void {
    var offset: usize = 0;
    while (offset < bytes.len) {
        const n = try std.posix.write(fd, bytes[offset..]);
        if (n == 0) return error.OutputClosed;
        offset += n;
    }
}

fn emit(allocator: std.mem.Allocator, value: result.Result, json: bool, exit_code: u8) noreturn {
    if (json) {
        const bytes = std.json.Stringify.valueAlloc(allocator, value, .{}) catch std.process.exit(1);
        writeAll(std.posix.STDOUT_FILENO, bytes) catch std.process.exit(1);
        writeAll(std.posix.STDOUT_FILENO, "\n") catch std.process.exit(1);
    } else if (value.@"error") |err| {
        writeAll(std.posix.STDERR_FILENO, err.code) catch std.process.exit(1);
        writeAll(std.posix.STDERR_FILENO, ": ") catch std.process.exit(1);
        writeAll(std.posix.STDERR_FILENO, err.message) catch std.process.exit(1);
        writeAll(std.posix.STDERR_FILENO, "\n") catch std.process.exit(1);
    }
    std.process.exit(exit_code);
}

pub fn main() void {
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
        writeAll(std.posix.STDOUT_FILENO, bytes) catch std.process.exit(1);
        return;
    }
    var value: result.Result = .{};
    value.backend.model = opts.model;
    value.verification.status = if (opts.check != null) .not_run else .not_requested;
    cli.validatePaths(opts) catch {
        value.@"error" = .{ .code = "usage_error", .message = "Workspace and additional context paths must be accessible directories." };
        emit(allocator, value, json, 2);
    };
    value.elapsed_ms = if (timer) |*t| t.read() / std.time.ns_per_ms else 0;
    value.@"error" = .{ .code = "unimplemented", .message = "M0 provides CLI validation only; backend execution and login are not implemented." };
    emit(allocator, value, opts.json, 1);
}

test {
    _ = @import("cli.zig");
    _ = @import("result.zig");
}
