export interface TitleBarMouseInput {
  button: number;
  detail: number;
}

export interface TitleBarWindowActions {
  startDragging: () => Promise<void>;
  toggleMaximize: () => Promise<void>;
}

export async function handleTitleBarMouseDown(
  event: TitleBarMouseInput,
  actions: TitleBarWindowActions,
) {
  if (event.button !== 0) return;

  if (event.detail === 2) {
    await actions.toggleMaximize();
    return;
  }

  await actions.startDragging();
}
