const std = @import("std");

// Fixed-capacity retention; input is always drained even after truncation.
pub const Buffer = struct {
    bytes: []u8,
    len: usize = 0,
    truncated: bool = false,

    pub fn init(a: std.mem.Allocator, limit: usize) !Buffer {
        return .{ .bytes = try a.alloc(u8, limit) };
    }
    pub fn slice(self: *const Buffer) []const u8 {
        return self.bytes[0..self.len];
    }
    pub fn prefix(self: *Buffer, data: []const u8) void {
        const n = @min(data.len, self.bytes.len - self.len);
        @memcpy(self.bytes[self.len..][0..n], data[0..n]);
        self.len += n;
        self.truncated = self.truncated or n < data.len;
    }
    pub fn tail(self: *Buffer, data: []const u8) void {
        if (data.len >= self.bytes.len) {
            self.truncated = self.truncated or self.len > 0 or data.len > self.bytes.len;
            @memcpy(self.bytes, data[data.len - self.bytes.len ..]);
            self.len = self.bytes.len;
        } else {
            const discard = (self.len + data.len) -| self.bytes.len;
            self.truncated = self.truncated or discard > 0;
            std.mem.copyForwards(u8, self.bytes, self.bytes[discard..self.len]);
            self.len -= discard;
            @memcpy(self.bytes[self.len..][0..data.len], data);
            self.len += data.len;
        }
    }
    // Replace invalid bytes (including cut UTF-8 sequences) without growing output.
    pub fn text(self: *Buffer) []const u8 {
        var i: usize = 0;
        while (i < self.len) {
            const n = std.unicode.utf8ByteSequenceLength(self.bytes[i]) catch 0;
            if (n == 0 or i + n > self.len or !std.unicode.utf8ValidateSlice(self.bytes[i..][0..n])) {
                self.bytes[i] = '?';
                i += 1;
            } else i += n;
        }
        return self.slice();
    }
};

pub const Events = struct {
    line: Buffer,
    summary: Buffer,
    completed: bool = false,
    failed: bool = false,
    protocol_error: bool = false,
    too_large: bool = false,

    pub fn init(a: std.mem.Allocator, event_limit: usize, output_limit: usize) !Events {
        return .{ .line = try Buffer.init(a, event_limit), .summary = try Buffer.init(a, output_limit) };
    }
    pub fn feed(self: *Events, bytes: []const u8) void {
        for (bytes) |byte| {
            if (byte == '\n') {
                self.event();
                self.line.len = 0;
            } else if (self.line.len < self.line.bytes.len) {
                self.line.bytes[self.line.len] = byte;
                self.line.len += 1;
            } else self.too_large = true;
        }
    }
    pub fn finish(self: *Events) void {
        // JSONL requires a newline, including on the final event.
        if (self.line.len != 0) self.protocol_error = true;
    }
    fn event(self: *Events) void {
        if (self.too_large or self.protocol_error) return;
        const parsed = std.json.parseFromSlice(std.json.Value, std.heap.page_allocator, self.line.slice(), .{ .allocate = .alloc_always }) catch {
            self.protocol_error = true;
            return;
        };
        defer parsed.deinit();
        const kind = field(parsed.value, "type") orelse {
            self.protocol_error = true;
            return;
        };
        if (kind != .string) {
            self.protocol_error = true;
            return;
        }
        if (std.mem.eql(u8, kind.string, "turn.completed")) {
            if (self.completed or !validUsage(field(parsed.value, "usage"))) self.protocol_error = true;
            self.completed = true;
        } else if (self.completed and (std.mem.eql(u8, kind.string, "turn.started") or
            std.mem.eql(u8, kind.string, "item.started") or std.mem.eql(u8, kind.string, "item.updated")))
        {
            self.protocol_error = true;
        } else if (std.mem.eql(u8, kind.string, "turn.failed") or std.mem.eql(u8, kind.string, "error")) {
            self.failed = true;
        } else if (std.mem.eql(u8, kind.string, "item.completed")) {
            const item = field(parsed.value, "item") orelse {
                self.protocol_error = true;
                return;
            };
            const item_type = field(item, "type") orelse {
                self.protocol_error = true;
                return;
            };
            if (item_type != .string) {
                self.protocol_error = true;
                return;
            }
            // Tool failures may recover; error items also carry nonfatal warnings.
            // Final turn/exit status decides completion, not individual items.
            if (std.mem.eql(u8, item_type.string, "agent_message")) {
                const text = field(item, "text") orelse {
                    self.protocol_error = true;
                    return;
                };
                if (text != .string or self.completed) {
                    self.protocol_error = true;
                    return;
                }
                self.summary.len = 0;
                self.summary.truncated = false;
                self.summary.prefix(text.string);
            }
        }
    }
};

fn field(value: std.json.Value, key: []const u8) ?std.json.Value {
    return if (value == .object) value.object.get(key) else null;
}

// Pinned Codex completion schema; cache writes are optional with a zero default.
fn validUsage(value: ?std.json.Value) bool {
    const usage = value orelse return false;
    for ([_][]const u8{ "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens" }) |name| {
        const count = field(usage, name) orelse return false;
        if (count != .integer) return false;
    }
    if (field(usage, "cache_write_input_tokens")) |count| {
        if (count != .integer) return false;
    }
    return true;
}

test "bounded retention and UTF-8 repair" {
    var b = try Buffer.init(std.testing.allocator, 3);
    defer std.testing.allocator.free(b.bytes);
    b.prefix("ab☃");
    try std.testing.expectEqualStrings("ab?", b.text());
    try std.testing.expect(b.truncated);
    b.tail("xyzq");
    try std.testing.expectEqualStrings("yzq", b.text());
}
