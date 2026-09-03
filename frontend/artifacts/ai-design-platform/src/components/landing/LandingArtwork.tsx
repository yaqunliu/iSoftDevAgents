/**
 * 接口注释：
 * 两块深色区域用的抽象配图。纯内联 SVG，不引用任何外部图片。
 *
 * 设计注释：
 * 深色块里刻意不放产品截图。三个理由：
 *   1. 截图会把官网的寿命绑在某一版 UI 上，产品一改版官网就开始说谎；
 *   2. 缩到官网尺寸后，截图里的文字必然糊成一片，读者看不清反而降低信任；
 *   3. 参考稿 SYMPHONY 的深色块（.showcase）本身就是抽象大图而不是界面截图，
 *      那份克制正是"编辑设计"气质的一部分。
 *
 * 原因注释：
 * 用内联 SVG 而不是 png/jpg 或图床链接，是为了：
 *   - 零网络请求，企业内网离线部署也能正常显示；
 *   - 矢量，任何分辨率都不糊；
 *   - 颜色走 currentColor，深浅主题都能用，不需要准备两套图；
 *   - 不往仓库里塞二进制文件，代码审查时改动可读。
 */

/**
 * 接力图：五个节点沿一条主轴依次交接，节点尺寸递减代表阶段推进。
 * 抽象表达"接力"这件事，但刻意不画成流程图——它是装饰，不是说明图，
 * 真正的流程说明在左侧的文字和阶段列表里。
 */
export function RelayArtwork({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 640 400"
      className={className}
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid slice"
    >
      {/* 主轴 */}
      <line x1="0" y1="200" x2="640" y2="200" stroke="currentColor" strokeWidth="1" opacity="0.28" />

      {/* 五个交接节点。半径递减，视觉上形成"逐级收敛"的方向感。 */}
      {[
        { cx: 88, r: 52 },
        { cx: 216, r: 44 },
        { cx: 336, r: 36 },
        { cx: 448, r: 28 },
        { cx: 552, r: 20 },
      ].map((node, index) => (
        <g key={node.cx}>
          <circle
            cx={node.cx}
            cy="200"
            r={node.r}
            stroke="currentColor"
            strokeWidth="1"
            opacity={0.5 - index * 0.06}
          />
          <circle cx={node.cx} cy="200" r="2.5" fill="currentColor" opacity={0.75 - index * 0.1} />
        </g>
      ))}

      {/* 上下两组游离细线，制造纵深，避免整幅图塌在一条水平线上 */}
      {[92, 128, 272, 308].map((y, index) => (
        <line
          key={y}
          x1={index % 2 === 0 ? 120 : 240}
          y1={y}
          x2={index % 2 === 0 ? 520 : 640}
          y2={y}
          stroke="currentColor"
          strokeWidth="1"
          opacity="0.1"
        />
      ))}
    </svg>
  );
}

/**
 * 信号图：一组等距的竖向刻度，高度按确定的公式起伏。
 *
 * 教学注释：
 * 高度用 index 算出来而不是随机数，是有意的——随机高度每次刷新都不一样，
 * 而且在 SSR 或者快照测试里会产生不稳定的输出。
 * 确定性公式看起来同样自然，但结果可复现。
 */
export function SignalArtwork({ className = "" }: { className?: string }) {
  const bars = Array.from({ length: 48 }, (_, index) => {
    const wave = Math.sin(index * 0.42) * 0.5 + Math.sin(index * 0.17) * 0.5;
    return {
      x: index * 13 + 8,
      height: 24 + Math.abs(wave) * 96,
      opacity: 0.18 + Math.abs(wave) * 0.34,
    };
  });

  return (
    <svg viewBox="0 0 640 200" className={className} fill="none" aria-hidden="true">
      {bars.map((bar) => (
        <line
          key={bar.x}
          x1={bar.x}
          y1={100 - bar.height / 2}
          x2={bar.x}
          y2={100 + bar.height / 2}
          stroke="currentColor"
          strokeWidth="1.5"
          opacity={bar.opacity}
        />
      ))}
    </svg>
  );
}
