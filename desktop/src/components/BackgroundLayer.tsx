import type { UIConfig } from "../types";

interface Props {
  config: UIConfig;
  backgroundDataUrl: string;
  logo: string;
}

export function BackgroundLayer({ config, backgroundDataUrl, logo }: Props) {
  const opacity = Math.max(0, Math.min(1, config.background_opacity));
  const tintOpacity = backgroundDataUrl ? 1 - opacity : 1;
  const shouldBlur = config.background_blur && opacity < 1;
  const style = backgroundDataUrl
    ? {
        backgroundImage: `url("${backgroundDataUrl}")`,
        backgroundSize: config.background_mode,
        opacity,
        filter: shouldBlur ? "blur(18px) scale(1.04)" : "none"
      }
    : undefined;

  return (
    <div className="background-stage" aria-hidden="true">
      {backgroundDataUrl ? <div className="custom-bg" style={style} /> : <img className="watermark-logo" src={logo} alt="" />}
      <div className="background-tint" style={{ opacity: tintOpacity }} />
    </div>
  );
}
