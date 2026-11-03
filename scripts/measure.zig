// Maintainer-only native launcher: avoid Python's pre-exec RSS floor in wait4.
const std = @import("std");
const c = @cImport({
    @cInclude("sys/types.h");
    @cInclude("sys/wait.h");
    @cInclude("sys/resource.h");
    @cInclude("time.h");
    @cInclude("unistd.h");
    @cInclude("fcntl.h");
    @cInclude("signal.h");
});

fn now() i64 {
    var value: c.struct_timespec = undefined;
    if (c.clock_gettime(c.CLOCK_MONOTONIC, &value) != 0) std.process.exit(1);
    return @as(i64, @intCast(value.tv_sec)) * 1_000_000_000 + value.tv_nsec;
}

pub fn main() !void {
    const args = try std.process.argsAlloc(std.heap.page_allocator);
    defer std.process.argsFree(std.heap.page_allocator, args);
    if (args.len != 3) return error.Usage;
    const null_fd = c.open("/dev/null", c.O_RDWR);
    if (null_fd < 0) return error.Open;
    defer _ = c.close(null_fd);
    const start = now();
    const pid = c.fork();
    if (pid < 0) return error.Fork;
    if (pid == 0) {
        if (c.dup2(null_fd, 0) < 0 or c.dup2(null_fd, 1) < 0 or c.dup2(null_fd, 2) < 0) c._exit(126);
        var argv = [_:null]?[*:0]const u8{ args[1].ptr, args[2].ptr };
        _ = c.execv(args[1].ptr, @ptrCast(&argv));
        c._exit(127);
    }
    var status: c_int = 0;
    var usage: std.c.rusage = undefined;
    while (true) {
        const observed = std.c.wait4(pid, &status, c.WNOHANG, &usage);
        if (observed == pid) break;
        if (observed < 0) return error.Wait;
        if (now() - start > 10_000_000_000) {
            // This child remains unreaped, so its identifier cannot be recycled.
            _ = c.kill(pid, c.SIGKILL);
            _ = std.c.wait4(pid, &status, 0, &usage);
            return error.Timeout;
        }
        _ = c.usleep(100);
    }
    const elapsed = now() - start;
    if (status != 0) return error.ChildFailed;
    const rss = @as(u64, @intCast(usage.maxrss)) * (if (@import("builtin").os.tag == .linux) @as(u64, 1024) else 1);
    var buffer: [256]u8 = undefined;
    const output = try std.fmt.bufPrint(&buffer, "{{\"elapsed_ns\":{d},\"peak_rss_bytes\":{d}}}\n", .{ elapsed, rss });
    if (c.write(1, output.ptr, output.len) != output.len) return error.Write;
}
