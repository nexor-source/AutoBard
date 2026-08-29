# Quarantine manifest

- Case: `7.0_64_create_thread_safe`
- Quarantined at: `2026-08-24 09:40:01 +08:00`
- Archive encryption: AES-256-CBC with PBKDF2
- Analysis password: `infected`
- Known C2 endpoint: `154.82.93.152:443`

## Key artifacts

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| Original outer executable (`D:\7.0_64_create_thread_safe.exe`) | 123,307 bytes | `8FDF00F61A4953846BEDC651F05BBD09B0247D9781C89DCE98FDDE72F18D9656` |
| ProgramData cache (`C:\ProgramData\853EAFC200002A0D\1`) | 261,503 bytes | `CD91509529CC740A2FD98C9BB034067E99248BD148945DFF91A63628ACF7AE65` |
| Unpacked stage 2 (`stage2_unpacked.exe.bin`) | 518,656 bytes | `C2D36D068753504AF6DF0C218F54AF2E6CFF95F935DB69A5D55AFB636B0060F3` |
| Final decoded stage 1 payload (`payload_final.bin`) | 18,307 bytes | `2065E6DEB694BC2D0D6D8F45650BF2D2BDF395DF0CAB28A9B94E26BCD7C04DF8` |

During the initial quarantine pass, the original outer executable was no longer present at its recorded path. It was later found at `D:\suspicious\7.0_64_create_thread_safe.exe`; its size and SHA-256 matched the earlier report exactly, and it was added to a separate encrypted archive. The ProgramData cache and binary analysis artifacts were also selected for quarantine.

No matching active process (apart from the inspection shell itself), active connection to `154.82.93.152`, Run/RunOnce entry, scheduled task, or service was found using these known indicators. This is an indicator-based check, not proof that the host is fully clean.

## Final isolation result

- Encrypted archive: `D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\sample_bundle.tar.aes256`
- Archive SHA-256: `2B990CF5FD361FC621C82DF024E3242A579C32BDD42FB06A8CB85F6A202120F5`
- Archive round-trip verification: passed (37 files extracted; stage 2 and cache hashes matched)
- Residual archive: `D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\residual_bundle.tar.aes256`
- Residual archive SHA-256: `75F8B884FE1BE654FC9BBCAEB14D23C6FF87C1827D85DCA145CFCAFC2D57F760`
- Residual archive verification: passed (`GROUP`, `INSTALL_TIME`, `REMARK`, and `Modules\x64\index.dat` hashes matched)
- Original outer executable archive: `D:\malware_quarantine\7.0_64_create_thread_safe_2026-08-24\outer_original_bundle.tar.aes256`
- Original outer executable archive SHA-256: `895CECB0409273AA7A7DE70D117DB3CF8139379DC5D79CEDA77AEE0A8FE5893D`
- Original outer executable verification: passed (extracted SHA-256 matched `8FDF00F61A4953846BEDC651F05BBD09B0247D9781C89DCE98FDDE72F18D9656`)
- Direct binary artifacts removed from `reverse_analysis/output`: 34
- Original executable removed from `D:\suspicious`: yes
- Entire related ProgramData directory removed: yes
- Unencrypted staging and verification copies removed: yes

Only decrypt and extract the archive inside an offline disposable virtual machine:

```powershell
& 'D:\workApp\Anaconda\Library\bin\openssl.exe' enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in 'sample_bundle.tar.aes256' -out 'sample_bundle.tar' -pass pass:infected
tar.exe -xf 'sample_bundle.tar'
```
