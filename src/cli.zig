const std = @import("std");

pub const version = "0.1.0-dev";
pub const prompt_limit = 1024 * 1024;
pub const Command = enum { help, version, run, login, run_help, login_help };
pub const Options = struct {
    command: Command = .help,
    model: ?[]const u8 = null,
    workspace: []const u8 = ".",
    add_dirs: std.ArrayList([]const u8) = .empty,
    check: ?[]const u8 = null,
    prompt: ?[]const u8 = null,
    json: bool = false,
    no_input: bool = false,
    timeout: u32 = 600,
    login_timeout: u32 = 300,
    output_limit: u32 = 65536,
    event_limit: u32 = 1048576,
    codex: []const u8 = "codex",
};
pub const ParseError = error{ Usage, OutOfMemory };

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

// Discover output mode even when parsing fails before reaching --json.
pub fn wantsJson(args: []const []const u8) bool {
    for (args) |arg| {
        if (eq(arg, "--")) break;
        if (eq(arg, "--json")) return true;
    }
    return false;
}

fn positive(value: []const u8, max: u32) ParseError!u32 {
    if (value.len == 0) return error.Usage;
    for (value) |c| if (c < '0' or c > '9') return error.Usage;
    const n = std.fmt.parseInt(u32, value, 10) catch return error.Usage;
    if (n == 0 or n > max) return error.Usage;
    return n;
}

pub fn parse(allocator: std.mem.Allocator, args: []const []const u8, env_model: ?[]const u8) ParseError!Options {
    var opts: Options = .{};
    if (args.len == 0) return error.Usage;
    for (args) |arg| {
        if (!std.unicode.utf8ValidateSlice(arg) or std.mem.indexOfScalar(u8, arg, 0) != null) return error.Usage;
    }
    if (eq(args[0], "--help") or eq(args[0], "--version")) {
        if (args.len != 1) return error.Usage;
        opts.command = if (eq(args[0], "--help")) .help else .version;
        return opts;
    }
    if (eq(args[0], "run")) opts.command = .run else if (eq(args[0], "login")) opts.command = .login else return error.Usage;
    var positional = false;
    var i: usize = 1;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (!positional and eq(arg, "--")) {
            positional = true;
            continue;
        }
        if (!positional and eq(arg, "--help")) {
            opts.command = if (opts.command == .run) .run_help else .login_help;
            return opts;
        }
        if (!positional and eq(arg, "--no-input")) {
            opts.no_input = true;
        } else if (!positional and eq(arg, "--json") and opts.command == .run) {
            opts.json = true;
        } else if (!positional and std.mem.startsWith(u8, arg, "--")) {
            if (i + 1 >= args.len) return error.Usage;
            i += 1;
            const value = args[i];
            if (value.len == 0 or std.mem.startsWith(u8, value, "--")) return error.Usage;
            if (eq(arg, "--login-timeout")) {
                opts.login_timeout = try positive(value, 86400);
            } else if (opts.command != .run) {
                return error.Usage;
            } else if (eq(arg, "--model")) {
                opts.model = value;
            } else if (eq(arg, "--workspace")) {
                opts.workspace = value;
            } else if (eq(arg, "--add-dir")) {
                try opts.add_dirs.append(allocator, value);
            } else if (eq(arg, "--check")) {
                opts.check = value;
            } else if (eq(arg, "--codex")) {
                opts.codex = value;
            } else if (eq(arg, "--timeout")) {
                opts.timeout = try positive(value, 86400);
            } else if (eq(arg, "--output-limit")) {
                opts.output_limit = try positive(value, 16777216);
            } else if (eq(arg, "--event-limit")) {
                opts.event_limit = try positive(value, 16777216);
            } else return error.Usage;
        } else {
            if (opts.command != .run or opts.prompt != null) return error.Usage;
            if (!positional and arg.len > 0 and arg[0] == '-' and !eq(arg, "-")) return error.Usage;
            if (arg.len == 0 or arg.len > prompt_limit) return error.Usage;
            opts.prompt = arg;
        }
    }
    if (opts.command == .run) {
        if (opts.model == null) opts.model = env_model;
        const model = opts.model orelse return error.Usage;
        if (model.len == 0 or !std.unicode.utf8ValidateSlice(model)) return error.Usage;
    }
    return opts;
}

pub fn validatePaths(opts: Options) error{Usage}!void {
    if (opts.command != .run) return;
    try directory(opts.workspace);
    // Relative context paths are relative to the caller, like --workspace.
    for (opts.add_dirs.items) |path| try directory(path);
}

fn directory(path: []const u8) error{Usage}!void {
    var dir = std.fs.cwd().openDir(path, .{}) catch return error.Usage;
    dir.close();
}

pub const help =
    \\zigagent — Codex supervisor (M0 CLI harness)
    \\Usage: zigagent run [options] [PROMPT|-]
    \\       zigagent login [--login-timeout SECONDS] [--no-input]
    \\       zigagent --help
    \\       zigagent --version
    \\Use run --help or login --help for options. Execution is unimplemented in M0.
    \\
;
pub const run_help =
    \\Usage: zigagent run [options] [PROMPT|-]
    \\  --model NAME             Required; overrides ZIGAGENT_MODEL
    \\  --workspace PATH         Working directory (default: current directory)
    \\  --add-dir PATH           Repeatable context directory, not an access boundary
    \\  --check COMMAND          Caller check through /bin/sh -c (M3)
    \\  --json                   One versioned result on stdout
    \\  --no-input               Disable login interaction
    \\  --timeout SECONDS        Execution/preflight deadline (default: 600; max: 86400)
    \\  --login-timeout SECONDS  Login deadline (default: 300; max: 86400)
    \\  --output-limit BYTES     Retained buffer limit (default: 65536; max: 16777216)
    \\  --event-limit BYTES      Event limit (default: 1048576; max: 16777216)
    \\  --codex PATH             Backend executable (default: codex through PATH)
    \\  --help                   Show this help without a backend
    \\All limits are positive integers. -- ends option parsing; prompt is one argument.
    \\PROMPT is capped at 1 MiB. - or omitted prompt selects nonterminal stdin (M1).
    \\M0 validates arguments and directories; execution and stdin reading are unimplemented.
    \\
;
pub const login_help =
    \\Usage: zigagent login [--login-timeout SECONDS] [--no-input]
    \\  --login-timeout SECONDS  Positive integer (default: 300; max: 86400)
    \\  --no-input               Disable login interaction
    \\  --help                   Show this help without a backend
    \\Login is unimplemented in M0.
    \\
;

test "positive limits reject signs, zero, overflow and excess" {
    try std.testing.expectEqual(@as(u32, 86400), try positive("86400", 86400));
    for ([_][]const u8{ "", "0", "+1", "-1", "1.0", " 1", "86401", "4294967296", "9999999999999999999999" }) |v| {
        try std.testing.expectError(error.Usage, positive(v, 86400));
    }
}

test "defaults and model precedence" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const defaults = try parse(arena.allocator(), &.{ "run", "hello" }, "environment");
    try std.testing.expectEqualStrings("environment", defaults.model.?);
    try std.testing.expectEqual(@as(u32, 600), defaults.timeout);
    try std.testing.expectEqual(@as(u32, 300), defaults.login_timeout);
    try std.testing.expectEqual(@as(u32, 65536), defaults.output_limit);
    try std.testing.expectEqual(@as(u32, 1048576), defaults.event_limit);
    const explicit = try parse(arena.allocator(), &.{ "run", "--model", "flag", "hello" }, "environment");
    try std.testing.expectEqualStrings("flag", explicit.model.?);
    try std.testing.expectError(error.Usage, parse(arena.allocator(), &.{"run"}, null));
}

test "delimiter and repeated context paths" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const opts = try parse(arena.allocator(), &.{ "run", "--add-dir", "a", "--add-dir", "b", "--", "--json" }, "m");
    try std.testing.expectEqualStrings("--json", opts.prompt.?);
    try std.testing.expect(!opts.json);
    try std.testing.expectEqual(@as(usize, 2), opts.add_dirs.items.len);
    try std.testing.expect(!wantsJson(&.{ "run", "--", "--json" }));
}

test "prompt size bound and invalid UTF-8" {
    const huge = try std.testing.allocator.alloc(u8, prompt_limit + 1);
    defer std.testing.allocator.free(huge);
    @memset(huge, 'x');
    try std.testing.expectError(error.Usage, parse(std.testing.allocator, &.{ "run", huge }, "m"));
    try std.testing.expectError(error.Usage, parse(std.testing.allocator, &.{ "run", "\xff" }, "m"));
}
