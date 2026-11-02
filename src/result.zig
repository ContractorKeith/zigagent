const std = @import("std");

pub const Status = enum { completed, failed, timed_out, cancelled };
pub const VerificationStatus = enum { not_requested, not_run, passed, failed };
pub const Result = struct {
    schema_version: u8 = 1,
    status: Status = .failed,
    summary: []const u8 = "",
    verification: struct {
        status: VerificationStatus = .not_requested,
        exit_code: ?i32 = null,
        output: []const u8 = "",
        truncated: bool = false,
    } = .{},
    elapsed_ms: u64 = 0,
    @"error": ?struct { code: []const u8, message: []const u8 } = null,
    diagnostics: struct { output: []const u8 = "", truncated: bool = false } = .{},
    summary_truncated: bool = false,
    backend: struct { name: []const u8 = "codex", version: ?[]const u8 = null, model: ?[]const u8 = null } = .{},
};

test "schema serializes errors with JSON escaping" {
    const value: Result = .{ .@"error" = .{ .code = "usage_error", .message = "quote\"\n\\\t" } };
    const json = try std.json.Stringify.valueAlloc(std.testing.allocator, value, .{});
    defer std.testing.allocator.free(json);
    const parsed = try std.json.parseFromSlice(std.json.Value, std.testing.allocator, json, .{});
    defer parsed.deinit();
    try std.testing.expectEqualStrings("quote\"\n\\\t", parsed.value.object.get("error").?.object.get("message").?.string);
    try std.testing.expectEqual(@as(i64, 1), parsed.value.object.get("schema_version").?.integer);
}
