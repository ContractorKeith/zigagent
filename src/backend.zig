const std = @import("std");
const cli = @import("cli.zig");
const process = @import("process.zig");
const stream = @import("stream.zig");
const Result = @import("result.zig").Result;

fn fail(value: *Result, code: []const u8, message: []const u8, exit: u8) u8 {
    value.@"error" = .{ .code = code, .message = message };
    if (exit == 124) value.status = .timed_out;
    return exit;
}
fn diagnostics(value: *Result, capture: *process.Capture) void {
    value.diagnostics = .{ .output = capture.diagnostics.text(), .truncated = capture.diagnostics.truncated };
}

pub fn run(a: std.mem.Allocator, opts: cli.Options, value: *Result) !u8 {
    if (opts.command == .login) return login(a, opts, value);
    if (opts.check != null) return fail(value, "unimplemented", "Caller checks are M3; --check is rejected before backend execution.", 1);
    var preflight = try process.Deadline.init(opts.timeout);
    const prompt = if (opts.prompt == null or std.mem.eql(u8, opts.prompt.?, "-"))
        process.readPrompt(a, cli.prompt_limit, &preflight) catch |err| {
            if (err == error.Interrupted or err == error.Terminated or err == error.OutputClosed) return err;
            return if (err == error.TimedOut) fail(value, "timed_out", "Prompt input deadline exceeded.", 124) else fail(value, "usage_error", "Provide a nonempty UTF-8 prompt up to 1 MiB; stdin must be nonterminal.", 2);
        }
    else
        opts.prompt.?;
    var probe = try process.Capture.init(a, opts.output_limit);
    process.run(a, &.{ opts.codex, "--version" }, null, &preflight, &probe) catch |err| return launchFailure(value, err);
    diagnostics(value, &probe);
    if (probe.timed_out) return fail(value, "timed_out", "Backend preflight deadline exceeded.", 124);
    const version = std.mem.trim(u8, probe.output.slice(), "\r\n");
    if (!probe.exit_zero or probe.output.truncated or !std.mem.eql(u8, version, "codex-cli 0.166.0")) return fail(value, "backend_incompatible", "Expected supported Codex version: codex-cli 0.166.0.", 3);
    value.backend.version = "0.166.0";
    // Verify required capabilities before authentication or a task-bearing request.
    var help = try process.Capture.init(a, opts.output_limit);
    // Help exceeds the normal probe cap; still a fixed finite input bound.
    help.output = try stream.Buffer.init(a, 65536);
    try process.run(a, &.{ opts.codex, "exec", "--help" }, null, &preflight, &help);
    diagnostics(value, &help);
    if (help.timed_out) return fail(value, "timed_out", "Backend capability probe deadline exceeded.", 124);
    for ([_][]const u8{ "--json", "--ephemeral", "--color", "--model", "--cd", "--add-dir", "--ignore-user-config", "--ignore-rules", "--dangerously-bypass-approvals-and-sandbox" }) |flag| {
        var tokens = std.mem.tokenizeAny(u8, help.output.slice(), " \t\r\n,=");
        var found = false;
        while (tokens.next()) |token| {
            if (std.mem.eql(u8, token, flag)) found = true;
        }
        if (!help.exit_zero or help.output.truncated or !found) return fail(value, "backend_capability", "Codex lacks a required controlled-execution capability.", 3);
    }
    var auth = try process.Capture.init(a, opts.output_limit);
    try process.run(a, &.{ opts.codex, "login", "status" }, null, &preflight, &auth);
    diagnostics(value, &auth);
    if (auth.timed_out) return fail(value, "timed_out", "Authentication probe deadline exceeded.", 124);
    switch (authState(&auth)) {
        .ready => {},
        .required => {
            const code = try login(a, opts, value);
            if (code != 0) return code;
        },
        .failed => return fail(value, "authentication_failed", "Unexpected Codex login status; ChatGPT authentication is required.", 4),
    }
    // Successful probe chatter is not a run diagnostic.
    value.diagnostics = .{};
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(a, &.{ opts.codex, "exec", "--json", "--ephemeral", "--color", "never", "--ignore-user-config", "--ignore-rules", "--dangerously-bypass-approvals-and-sandbox", "-c", "forced_login_method=\"chatgpt\"", "--disable", "hooks", "--disable", "plugins", "--disable", "apps", "--disable", "memories", "--model", opts.model.?, "--cd", try std.fs.cwd().realpathAlloc(a, opts.workspace) });
    for (opts.add_dirs.items) |dir| try argv.appendSlice(a, &.{ "--add-dir", try std.fs.cwd().realpathAlloc(a, dir) });
    try argv.append(a, "-");
    var events = try stream.Events.init(a, opts.event_limit, opts.output_limit);
    var capture = try process.Capture.init(a, opts.output_limit);
    capture.events = &events;
    var execution = try process.Deadline.init(opts.timeout);
    try process.run(a, argv.items, prompt, &execution, &capture);
    diagnostics(value, &capture);
    value.summary = events.summary.text();
    value.summary_truncated = events.summary.truncated;
    if (capture.timed_out) return fail(value, "timed_out", "Backend execution deadline exceeded; edits are preserved.", 124);
    if (events.too_large) return fail(value, "event_too_large", "Backend JSONL event exceeded --event-limit.", 1);
    if (events.protocol_error) return fail(value, "protocol_error", "Malformed or incomplete backend JSONL.", 1);
    if (!capture.exit_zero or events.failed or capture.input_incomplete or capture.cleanup_incomplete) return fail(value, "backend_failed", "Backend exited unsuccessfully or emitted a failure; edits are preserved.", 1);
    if (!events.completed) return fail(value, "protocol_error", "Backend exited without a recognized completion event.", 1);
    value.status = .completed;
    return 0;
}

fn launchFailure(value: *Result, err: anyerror) anyerror!u8 {
    return switch (err) {
        error.FileNotFound => fail(value, "backend_missing", "Install Codex 0.166.0 or supply --codex PATH for run.", 3),
        error.AccessDenied, error.InvalidExe => fail(value, "backend_incompatible", "Codex is not an executable supported by this host.", 3),
        else => return err,
    };
}

const Auth = enum { ready, required, failed };
fn authState(auth: *process.Capture) Auth {
    if (auth.output.truncated or auth.probe_stderr.truncated or
        (auth.output.len != 0 and auth.probe_stderr.len != 0)) return .failed;
    const status = std.mem.trim(u8, if (auth.probe_stderr.len != 0) auth.probe_stderr.slice() else auth.output.slice(), "\r\n");
    if (auth.exit_zero and std.mem.eql(u8, status, "Logged in using ChatGPT")) return .ready;
    if (!auth.exit_zero and std.mem.eql(u8, status, "Not logged in")) return .required;
    return .failed;
}

fn login(a: std.mem.Allocator, opts: cli.Options, value: *Result) !u8 {
    if (opts.no_input) return fail(value, "authentication_required", "Login requires a controlling terminal and input enabled.", 4);
    const tty = process.openTerminal(false) catch
        return fail(value, "authentication_required", "Login requires a controlling terminal and input enabled.", 4);
    defer std.posix.close(tty);
    const output = try process.openTerminal(true);
    defer std.posix.close(output);
    var deadline = try process.Deadline.init(opts.login_timeout);
    var capture = try process.Capture.init(a, opts.output_limit);
    capture.terminal = tty;
    capture.terminal_output = output;
    process.run(a, &.{ opts.codex, "login" }, null, &deadline, &capture) catch |err| return launchFailure(value, err);
    if (capture.timed_out) return fail(value, "timed_out", "Official login deadline exceeded.", 124);
    if (capture.exit_signal == std.posix.SIG.INT) return error.Interrupted;
    if (capture.exit_signal == std.posix.SIG.TERM) return error.Terminated;
    if (!capture.exit_zero or capture.cleanup_incomplete) return fail(value, "authentication_failed", "Official Codex login failed.", 4);
    var auth = try process.Capture.init(a, opts.output_limit);
    try process.run(a, &.{ opts.codex, "login", "status" }, null, &deadline, &auth);
    if (auth.timed_out) return fail(value, "timed_out", "Post-login authentication deadline exceeded.", 124);
    if (authState(&auth) != .ready) return fail(value, "authentication_failed", "Official login did not establish ChatGPT authentication.", 4);
    if (opts.command == .login) {
        value.status = .completed;
        value.summary = "ChatGPT login verified.";
    }
    return 0;
}
