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
; 1. User data is never moved, never deleted, never at risk. Builds up to
;    v3.2.0 wrote runs into _internal\analysis-runs, and the app migrates them
;    on first launch - the installer runs before that. If either legacy data
;    directory is present, this hook does nothing at all: the payload is left
;    exactly as it is today, and cleanup waits for a later upgrade.
;
;    An earlier revision instead renamed _internal aside, excluded those two
;    directories while deleting, and renamed it back. That put user data under
;    a second name for the duration, and an interruption in that window left it
;    there for a later run to delete. Cleaning stale DLLs is not worth any path
;    that can lose a user's runs, so the whole window is gone: once the guard
;    above passes, everything under _internal is program payload.
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
;    condition directly - if the directory can be renamed, nothing inside it is
;    held open. A failed probe means the cleanup is skipped, which is exactly
;    today's behaviour. Renaming is also the deletion: the payload is deleted
;    under the temporary name, so there is no rename-back step to interrupt.
;
; 3. No half-deleted install. The template inserts this hook *before* its own
;    CheckIfAppIsRunning, so a running app would have its files deleted and the
;    user could then cancel at that prompt. The check is invoked here first, so
;    cancelling aborts before anything is removed and the template's later call
;    is a no-op. It does not make extraction infallible: a pre-clean turns
;    "stale files remain" into "files are missing" if extraction fails and the
;    user cancels there.

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

  StrCpy $R4 "$INSTDIR\resources\backend\sidecar\_internal"
  StrCpy $R5 "$INSTDIR\resources\backend\sidecar\_internal.old-payload"
  IfFileExists "$R4\*.*" 0 preinstall_done_${BCC_PREINSTALL_ID}

  ; Unmigrated user data from v3.2.0 and earlier. Leave everything alone; the
  ; app's migration has to run first. Cleanup resumes on a later upgrade.
  IfFileExists "$R4\analysis-runs\*.*" preinstall_done_${BCC_PREINSTALL_ID}
  IfFileExists "$R4\analysis-assets\*.*" preinstall_done_${BCC_PREINSTALL_ID}

  ; Past this point _internal holds only program payload, so a leftover copy
  ; from an interrupted run carries no user data and is safe to remove.
  RMDir /r "$R5"

  ; Probe for open handles by renaming, then delete under the temporary name.
  ; A mapped DLL makes the rename fail, which is the signal that the sidecar is
  ; still alive; give an orphaned one time to reach EOF and exit.
  StrCpy $R6 0
  preinstall_probe_${BCC_PREINSTALL_ID}:
    ClearErrors
    Rename "$R4" "$R5"
    IfErrors 0 preinstall_delete_${BCC_PREINSTALL_ID}
    IntOp $R6 $R6 + 1
    IntCmp $R6 20 preinstall_done_${BCC_PREINSTALL_ID} 0 preinstall_done_${BCC_PREINSTALL_ID}
    Sleep 500
    Goto preinstall_probe_${BCC_PREINSTALL_ID}

  preinstall_delete_${BCC_PREINSTALL_ID}:
  RMDir /r "$R5"

  preinstall_done_${BCC_PREINSTALL_ID}:
  Pop $R6
  Pop $R5
  Pop $R4

  !undef BCC_PREINSTALL_ID
!macroend
