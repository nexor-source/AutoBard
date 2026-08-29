/*
 * SAFE, NON-COMPILABLE C-LIKE DECOMPILATION OF THE CACHED SECOND STAGE
 *
 * Unpacked SHA-256:
 * C2D36D068753504AF6DF0C218F54AF2E6CFF95F935DB69A5D55AFB636B0060F3
 *
 * This reconstruction documents behavior.  It deliberately omits working
 * implementations of command execution, privilege/token operations, network
 * control, downloading, and in-memory code execution.
 */

enum FeatureKind {
    FEATURE_SCREENSHOT,
    FEATURE_CLIPBOARD,
    FEATURE_KEY_INPUT,
    FEATURE_FILTER,
    FEATURE_TCP_POLICY,
};

struct AgentContext {
    DMV2_Config config;
    MagnetWireV2 encrypted_transport;
    FeatureController features;
    CommandQueue commands;
    WorkerThreads workers;
    AtomicBool stopping;
};

static DeviceReport collect_device_report(void)
{
    DeviceReport r = {};
    r.windows_version       = query_windows_version_and_build();
    r.machine_guid          = read_registry_machine_guid();
    r.user_and_computer     = query_user_computer_and_sessions();
    r.memory_and_disks      = query_memory_disks_and_volumes();
    r.firmware_and_hardware = query_firmware_gpu_displays_and_devices();
    r.processes             = enumerate_processes_and_threads();
    r.installed_software    = enumerate_uninstall_registry();
    r.antivirus             = query_security_center_antivirus();
    r.network               = query_adapters_and_tcp_table();
    r.rdp_uac_state         = query_rdp_port_and_uac();
    return r;
}

static void start_feature_workers(AgentContext *ctx)
{
    /* Backends identified directly by strings/call paths:
       ScreenshotWinBackend, ClipboardWinBackend, InputCaptureWinBackend,
       NetworkTableWinBackend, FilterProbeWinBackend. */
    ctx->features.add(FEATURE_SCREENSHOT, make_screenshot_backend());
    ctx->features.add(FEATURE_CLIPBOARD,  make_clipboard_backend());
    ctx->features.add(FEATURE_KEY_INPUT,  make_key_input_backend());
    ctx->features.add(FEATURE_FILTER,     make_filter_probe_backend());
    ctx->features.add(FEATURE_TCP_POLICY,make_network_table_backend());
    ctx->features.start_configured_workers();
}

static CommandResult dispatch_remote_command(
    AgentContext *ctx, byte command, const byte *payload, size_t length)
{
    if (!validate_command_envelope(command, payload, length))
        return error("数据无效");

    switch (semantic_command_class(command)) {
    case CMD_DEVICE_REPORT:
        return send_device_report(collect_device_report());

    case CMD_CONFIGURE_FEATURES:
        return ctx->features.apply_signed_or_crc_checked_configuration(payload, length);

    case CMD_SCREENSHOT_NOW:
        return queue_screenshot_without_operational_details(ctx);

    case CMD_RUN_SHELL_SCRIPT:
        /* Real code locates cmd.exe, writes a temporary batch file, captures
           stdout/exit status through pipes, and supports "__CANCEL__". */
        return run_shell_command_safely_summarized(payload, length);

    case CMD_CREATE_PROCESS:
        return create_process_safely_summarized(payload, length);

    case CMD_DOWNLOAD_AND_EXECUTE:
        /* Real code uses WININET with a Chrome-like User-Agent and accepts a
           file up to 64 MiB.  Operational implementation omitted. */
        return download_execute_safely_summarized(payload, length);

    case CMD_EXECUTE_MEMORY_PAYLOAD:
        /* Real code allocates memory and transfers control with CreateThread.
           The reusable implementation is intentionally omitted. */
        return memory_payload_safely_summarized(payload, length);

    case CMD_FIREWALL_RULE:
        return firewall_change_safely_summarized(payload, length);

    case CMD_TCP_CONNECTION_ACTION:
        return tcp_table_action_safely_summarized(payload, length);

    case CMD_ELEVATED_PROCESS:
        /* Paths use SeDebugPrivilege, session tokens, winlogon/lsass and the
           TrustedInstaller service.  Operational token code omitted. */
        return elevated_process_safely_summarized(payload, length);

    case CMD_RESTART:
        queue_agent_restart();
        return status("正在重启");

    case CMD_UNINSTALL:
        queue_agent_uninstall();
        return status("正在卸载");

    case CMD_STOP_CURRENT_COMMAND:
        ctx->commands.cancel_current();
        return status("已停止当前命令");

    default:
        return error("未知命令");
    }
}

static unsigned agent_worker(void *opaque)
{
    AgentContext *ctx = opaque;
    start_feature_workers(ctx);

    while (!ctx->stopping) {
        if (!ctx->encrypted_transport.connected()) {
            ctx->encrypted_transport.connect_and_authenticate(
                ctx->config.server,
                ctx->config.port,
                ctx->config.handshake_field_16,
                ctx->config.pinned_key_or_identity_32
            );
        }

        Message m = ctx->encrypted_transport.receive();
        if (m.valid)
            dispatch_remote_command(ctx, m.type, m.payload, m.length);
        else
            reconnect_using_backup_address_list_after_delay();
    }
    return 0;
}

// Export RVA 0x48780.  Its name hash is 0x2EC07661, exactly what the outer
// reflective loader resolves and invokes.
export int DM_Start(const DMV2_Config *config)
{
    if (!validate_dmv2_config(config))
        return 0;

    AgentContext *ctx = initialize_global_agent_context(config, "Magnet");
    if (!ctx)
        return 0;

    ctx->workers.start(agent_worker, ctx);
    return 1;
}

// Export RVA 0x48788.
export void DM_Stop(void)
{
    AgentContext *ctx = get_global_agent_context();
    if (!ctx)
        return;
    ctx->stopping = true;
    ctx->encrypted_transport.close();
    ctx->features.stop_all();
    ctx->commands.cancel_current();
    ctx->workers.join_with_timeout();
    destroy_global_agent_context();
}
