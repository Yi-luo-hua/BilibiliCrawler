; Remove the previous build's sidecar payload before extracting this one.
;
; Why this is needed: Tauri's uninstall section is expanded at build time into
; one Delete per shipped file and contains no RMDir /r, so an uninstaller only
; removes what its own build shipped. The install section overwrites in place
; without a pre-clean, and update mode skips the uninstall entirely. Anything a
; previous build shipped and this one does not therefore survives both the
; upgrade and every later uninstall, sitting on the sidecar's sys.path where it
; stays importable. Measured between v3.3.0 and v3.4.0: three stale
; api-ms-win-* forwarder DLLs.
;
; Three properties this has to preserve:
;
; 1. Legacy user data. Builds up to v3.2.0 wrote runs into
;    _internal\analysis-runs, and the app migrates them to stable storage on
;    first launch. The installer runs before the app, so those directories are
;    skipped and left for that migration. They are excluded by name rather than
;    by skipping the whole cleanup, so a machine still holding them does not
;    lose cleanup forever - the migration copies but never deletes its source.
;
; 2. Nothing is deleted while the payload is in use. Closing the main binary is
;    not enough: the Python sidecar is a separate process name, is spawned
;    DETACHED_PROCESS, and its parent only calls child.kill() on a graceful
;    window close - a forced kill orphans it. It then keeps _internal DLLs
;    mapped until its stdin reaches EOF, which it cannot notice during the
;    startup wordcloud warm-up (documented as 30-120 s on a cold font cache).
;
;    Killing "sidecar.exe" by name is not the answer either: the bundled
;    nsis-process plugin matches on name alone, and that name is generic enough
;    that another program's process could be terminated. So this tests the
;    condition directly instead of guessing at processes - if the directory can
;    be renamed, nothing inside it is held open. A failed probe means the
;    cleanup is skipped entirely, which is exactly today's behaviour.
;
; 3. No half-deleted install. The template inserts this hook *before* its own
;    CheckIfAppIsRunning, so a running app would have its files deleted and the
;    user could then cancel at that prompt. The check is invoked here first, so
;    cancelling aborts before anything is removed and the template's later call
;    is a no-op. Deletion only starts once the probe has shown the tree is free,
;    which removes the main reason extraction would fail afterwards. It does not
;    make extraction infallible: a pre-clean necessarily turns "stale files
;    remain" into "files are missing" if extraction fails and the user cancels.

!macro NSIS_HOOK_PREINSTALL
  ; One id for every label below. ${__LINE__} is evaluated per line, so
  ; using it directly would give the definition and its Goto different names.
  !define BCC_PREINSTALL_ID ${__LINE__}
  ; Ask about (and close) a running app before deleting anything.
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; The template owns the register file across this section, so borrow and
  ; restore rather than assuming these are free.
  Push $R4
  Push $R5
  Push $R6
  Push $R7
  Push $R8

  StrCpy $R4 "$INSTDIR\resources\backend\sidecar\_internal"
  StrCpy $R7 "$INSTDIR\resources\backend\sidecar\_internal.cleanup-probe"
  IfFileExists "$R4\*.*" 0 preinstall_done_${BCC_PREINSTALL_ID}

  ; A stale probe directory means a previous run died between the two renames.
  ; Put it back rather than leaving the payload split across two names.
  IfFileExists "$R7\*.*" 0 preinstall_probe_${BCC_PREINSTALL_ID}
    RMDir /r "$R7"

  ; Probe for open handles by renaming the directory. A mapped DLL inside it
  ; makes this fail, which is the signal that the sidecar is still alive.
  ; Give an orphaned sidecar time to reach EOF and exit before giving up.
  preinstall_probe_${BCC_PREINSTALL_ID}:
  StrCpy $R8 0
  preinstall_probe_loop_${BCC_PREINSTALL_ID}:
    ClearErrors
    Rename "$R4" "$R7"
    IfErrors 0 preinstall_probe_ok_${BCC_PREINSTALL_ID}
    IntOp $R8 $R8 + 1
    IntCmp $R8 20 preinstall_done_${BCC_PREINSTALL_ID} 0 preinstall_done_${BCC_PREINSTALL_ID}
    Sleep 500
    Goto preinstall_probe_loop_${BCC_PREINSTALL_ID}

  preinstall_probe_ok_${BCC_PREINSTALL_ID}:
  ClearErrors
  Rename "$R7" "$R4"
  IfErrors 0 preinstall_clean_${BCC_PREINSTALL_ID}
    ; Nothing holds a handle, so this should not happen. Stop rather than leave
    ; the payload - including unmigrated user data - under the probe name.
    DetailPrint "Could not restore $R7; aborting to avoid a split payload."
    Abort

  preinstall_clean_${BCC_PREINSTALL_ID}:
  FindFirst $R5 $R6 "$R4\*"
  preinstall_loop_${BCC_PREINSTALL_ID}:
    StrCmp $R6 "" preinstall_close_${BCC_PREINSTALL_ID}
    StrCmp $R6 "." preinstall_next_${BCC_PREINSTALL_ID}
    StrCmp $R6 ".." preinstall_next_${BCC_PREINSTALL_ID}
    ; Unmigrated user data from v3.2.0 and earlier.
    StrCmp $R6 "analysis-runs" preinstall_next_${BCC_PREINSTALL_ID}
    StrCmp $R6 "analysis-assets" preinstall_next_${BCC_PREINSTALL_ID}
    IfFileExists "$R4\$R6\*.*" 0 preinstall_file_${BCC_PREINSTALL_ID}
      RMDir /r "$R4\$R6"
      Goto preinstall_next_${BCC_PREINSTALL_ID}
    preinstall_file_${BCC_PREINSTALL_ID}:
      Delete "$R4\$R6"
    preinstall_next_${BCC_PREINSTALL_ID}:
      FindNext $R5 $R6
      Goto preinstall_loop_${BCC_PREINSTALL_ID}
  preinstall_close_${BCC_PREINSTALL_ID}:
  FindClose $R5
  preinstall_done_${BCC_PREINSTALL_ID}:

  Pop $R8
  Pop $R7
  Pop $R6
  Pop $R5
  Pop $R4

  !undef BCC_PREINSTALL_ID
!macroend
