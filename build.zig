const std = @import("std");

pub fn build(b: *std.Build) void {
    // Use Zig's bundled glibc support rather than newer host startup objects
    // whose relocations the pinned compiler cannot link (e.g. Arch .sframe).
    const native = @import("builtin");
    const target = b.standardTargetOptions(.{ .default_target = if (native.os.tag == .linux) .{
        .cpu_arch = native.cpu.arch,
        .os_tag = .linux,
        .abi = .gnu,
        .glibc_version = .{ .major = 2, .minor = 28, .patch = 0 },
    } else .{} });
    const optimize = b.standardOptimizeOption(.{});
    const module = b.createModule(.{
        .root_source_file = b.path("src/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    module.link_libc = true;
    const exe = b.addExecutable(.{ .name = "zigagent", .root_module = module });
    b.installArtifact(exe);
    const tests = b.addTest(.{ .root_module = module });
    b.step("test", "Run unit tests").dependOn(&b.addRunArtifact(tests).step);
}
