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
; Two properties this has to preserve:
;
; 1. Legacy user data. Builds up to v3.2.0 wrote runs into
;    _internal\analysis-runs, and the app migrates them to stable storage on
;    first launch. The installer runs before the app, so those directories are
;    skipped and left for that migration. They are excluded by name rather than
;    by skipping the whole cleanup, so a machine still holding them does not
;    lose cleanup forever - the migration copies but never deletes its source.
;
; 2. No half-deleted install. The template inserts this hook *before* its own
;    CheckIfAppIsRunning, so a running app would have its files deleted and the
;    user could then cancel at that prompt. The check is invoked here first:
;    cancelling aborts before anything is removed, and the template's later call
;    becomes a no-op. After this hook the install proceeds without further
;    prompts, so a partially cleaned payload is always re-extracted.

!macro NSIS_HOOK_PREINSTALL
  ; One id for every label below. ${__LINE__} is evaluated per line, so
  ; using it directly would give the definition and its Goto different names.
  !define BCC_PREINSTALL_ID ${__LINE__}
  ; Ask about (and close) a running app before deleting anything.
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; The template owns the register file across this section, so borrow and
  ; restore rather than assuming R4-R6 are free.
  Push $R4
  Push $R5
  Push $R6

  StrCpy $R4 "$INSTDIR\resources\backend\sidecar\_internal"
  IfFileExists "$R4\*.*" 0 preinstall_done_${BCC_PREINSTALL_ID}

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

  Pop $R6
  Pop $R5
  Pop $R4

  !undef BCC_PREINSTALL_ID
!macroend
