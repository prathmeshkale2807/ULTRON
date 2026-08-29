import React, { useEffect, useRef } from 'react';

export type OrbState =
  | 'STANDBY'
  | 'WAKE_DETECTED'
  | 'LISTENING'
  | 'PROCESSING'
  | 'THINKING'
  | 'EXECUTING'
  | 'WAITING_FOR_CONFIRMATION'
  | 'SPEAKING'
  | 'ERROR'
  | 'CLOSED';

interface OrbCoreProps {
  state: OrbState;
  size?: number;
  interactive?: boolean;
  onClick?: () => void;
}

interface StateTheme {
  primary: string;
  secondary: string;
  glow: string;
  core: string;
  speed: number;
  particles: number;
  pulseScale: number;
}

const THEMES: Record<OrbState, StateTheme> = {
  STANDBY: {
    primary: 'rgba(0, 210, 255, 0.7)',
    secondary: 'rgba(0, 110, 255, 0.4)',
    glow: 'rgba(0, 190, 255, 0.25)',
    core: 'rgba(180, 240, 255, 0.9)',
    speed: 0.015,
    particles: 60,
    pulseScale: 1.03,
  },
  WAKE_DETECTED: {
    primary: 'rgba(255, 215, 0, 0.95)',
    secondary: 'rgba(0, 255, 230, 0.8)',
    glow: 'rgba(255, 220, 50, 0.5)',
    core: 'rgba(255, 255, 255, 1.0)',
    speed: 0.05,
    particles: 100,
    pulseScale: 1.25,
  },
  LISTENING: {
    primary: 'rgba(0, 255, 170, 0.9)',
    secondary: 'rgba(0, 180, 255, 0.7)',
    glow: 'rgba(0, 255, 180, 0.4)',
    core: 'rgba(210, 255, 240, 1.0)',
    speed: 0.035,
    particles: 90,
    pulseScale: 1.15,
  },
  PROCESSING: {
    primary: 'rgba(170, 80, 255, 0.95)',
    secondary: 'rgba(0, 180, 255, 0.8)',
    glow: 'rgba(160, 60, 255, 0.45)',
    core: 'rgba(240, 210, 255, 1.0)',
    speed: 0.06,
    particles: 120,
    pulseScale: 1.18,
  },
  THINKING: {
    primary: 'rgba(140, 60, 255, 0.95)',
    secondary: 'rgba(0, 230, 255, 0.75)',
    glow: 'rgba(130, 50, 255, 0.4)',
    core: 'rgba(230, 200, 255, 1.0)',
    speed: 0.05,
    particles: 110,
    pulseScale: 1.12,
  },
  EXECUTING: {
    primary: 'rgba(255, 140, 0, 0.95)',
    secondary: 'rgba(255, 215, 0, 0.8)',
    glow: 'rgba(255, 120, 0, 0.45)',
    core: 'rgba(255, 240, 200, 1.0)',
    speed: 0.07,
    particles: 130,
    pulseScale: 1.2,
  },
  WAITING_FOR_CONFIRMATION: {
    primary: 'rgba(255, 190, 0, 0.95)',
    secondary: 'rgba(255, 60, 0, 0.7)',
    glow: 'rgba(255, 180, 0, 0.5)',
    core: 'rgba(255, 255, 220, 1.0)',
    speed: 0.03,
    particles: 80,
    pulseScale: 1.15,
  },
  SPEAKING: {
    primary: 'rgba(0, 195, 255, 0.95)',
    secondary: 'rgba(130, 70, 255, 0.8)',
    glow: 'rgba(0, 180, 255, 0.5)',
    core: 'rgba(220, 245, 255, 1.0)',
    speed: 0.045,
    particles: 100,
    pulseScale: 1.22,
  },
  ERROR: {
    primary: 'rgba(255, 40, 40, 0.95)',
    secondary: 'rgba(180, 0, 0, 0.8)',
    glow: 'rgba(255, 30, 30, 0.5)',
    core: 'rgba(255, 200, 200, 1.0)',
    speed: 0.02,
    particles: 50,
    pulseScale: 1.08,
  },
  CLOSED: {
    primary: 'rgba(70, 80, 100, 0.4)',
    secondary: 'rgba(40, 50, 70, 0.3)',
    glow: 'rgba(50, 60, 80, 0.1)',
    core: 'rgba(120, 130, 150, 0.5)',
    speed: 0.005,
    particles: 20,
    pulseScale: 1.0,
  },
};

export function OrbCore({ state, size = 320, interactive = true, onClick }: OrbCoreProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<OrbState>(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let time = 0;

    // Particle nodes
    const particleCount = 120;
    const particles = Array.from({ length: particleCount }, () => ({
      angle: Math.random() * Math.PI * 2,
      radius: 30 + Math.random() * (size * 0.35),
      size: 1 + Math.random() * 2.5,
      speed: (Math.random() - 0.5) * 0.02,
      orbitSpeed: 0.005 + Math.random() * 0.015,
      tilt: (Math.random() - 0.5) * Math.PI,
      brightness: 0.3 + Math.random() * 0.7,
    }));

    const render = () => {
      const currentTheme = THEMES[stateRef.current] || THEMES.STANDBY;
      time += currentTheme.speed;

      ctx.clearRect(0, 0, size, size);
      const cx = size / 2;
      const cy = size / 2;
      const baseRadius = size * 0.22;

      // Dynamic breathing scale
      const pulse = 1 + (currentTheme.pulseScale - 1) * Math.sin(time * 3);
      const currentRadius = baseRadius * pulse;

      // 1. Ambient Outer Halo
      const outerGlow = ctx.createRadialGradient(cx, cy, currentRadius * 0.5, cx, cy, size * 0.48);
      outerGlow.addColorStop(0, currentTheme.glow);
      outerGlow.addColorStop(0.5, currentTheme.secondary);
      outerGlow.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = outerGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, size * 0.48, 0, Math.PI * 2);
      ctx.fill();

      // 2. Holographic Geometric Orbital Rings
      const ringCount = 3;
      for (let i = 0; i < ringCount; i++) {
        ctx.save();
        ctx.translate(cx, cy);
        const rotX = time * (0.8 + i * 0.3) * (i % 2 === 0 ? 1 : -1);
        const rotY = time * (0.6 + i * 0.2);
        ctx.rotate(rotX);

        ctx.beginPath();
        const rx = currentRadius * (1.3 + i * 0.25);
        const ry = currentRadius * (0.6 + i * 0.15) * Math.cos(rotY);
        ctx.ellipse(0, 0, rx, Math.max(ry, 2), rotY, 0, Math.PI * 2);
        ctx.strokeStyle = i === 0 ? currentTheme.primary : currentTheme.secondary;
        ctx.lineWidth = i === 0 ? 2 : 1;
        ctx.stroke();

        // Ring orbital beacon node
        const beaconAngle = time * (2 + i);
        const bx = rx * Math.cos(beaconAngle);
        const by = ry * Math.sin(beaconAngle);
        ctx.beginPath();
        ctx.arc(bx, by, 3, 0, Math.PI * 2);
        ctx.fillStyle = currentTheme.core;
        ctx.shadowColor = currentTheme.primary;
        ctx.shadowBlur = 10;
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.restore();
      }

      // 3. Orbital Particles Cloud
      particles.slice(0, currentTheme.particles).forEach((p) => {
        p.angle += p.orbitSpeed;
        const pr = p.radius * pulse;
        const px = cx + pr * Math.cos(p.angle);
        const py = cy + pr * Math.sin(p.angle) * Math.cos(p.tilt + time);

        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fillStyle = currentTheme.primary;
        ctx.globalAlpha = p.brightness * 0.8;
        ctx.shadowColor = currentTheme.primary;
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.globalAlpha = 1.0;
      });

      // 4. Inner Plasma Core with Radial Gradient
      const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, currentRadius);
      coreGrad.addColorStop(0, currentTheme.core);
      coreGrad.addColorStop(0.3, currentTheme.primary);
      coreGrad.addColorStop(0.8, currentTheme.secondary);
      coreGrad.addColorStop(1, 'rgba(0,0,0,0)');

      ctx.beginPath();
      ctx.arc(cx, cy, currentRadius, 0, Math.PI * 2);
      ctx.fillStyle = coreGrad;
      ctx.shadowColor = currentTheme.primary;
      ctx.shadowBlur = 25;
      ctx.fill();
      ctx.shadowBlur = 0;

      // 5. High-intensity Central Singularity
      ctx.beginPath();
      ctx.arc(cx, cy, currentRadius * 0.35, 0, Math.PI * 2);
      ctx.fillStyle = '#ffffff';
      ctx.shadowColor = '#ffffff';
      ctx.shadowBlur = 15;
      ctx.fill();
      ctx.shadowBlur = 0;

      // 6. Audio Waveform Spikes during SPEAKING / LISTENING
      if (stateRef.current === 'SPEAKING' || stateRef.current === 'LISTENING') {
        const spikeCount = 24;
        ctx.save();
        ctx.translate(cx, cy);
        for (let j = 0; j < spikeCount; j++) {
          const sAngle = (j / spikeCount) * Math.PI * 2 + time;
          const sLength = currentRadius * 1.1 + Math.sin(time * 8 + j * 1.5) * (baseRadius * 0.4);
          const sx = Math.cos(sAngle) * sLength;
          const sy = Math.sin(sAngle) * sLength;

          ctx.beginPath();
          ctx.moveTo(Math.cos(sAngle) * currentRadius, Math.sin(sAngle) * currentRadius);
          ctx.lineTo(sx, sy);
          ctx.strokeStyle = currentTheme.primary;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
        ctx.restore();
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [size]);

  return (
    <div
      onClick={interactive ? onClick : undefined}
      style={{
        width: size,
        height: size,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: interactive ? 'pointer' : 'default',
        position: 'relative',
        userSelect: 'none',
      }}
      title={interactive ? `ULTRON State: ${state} (Click for Push-To-Talk)` : `ULTRON: ${state}`}
    >
      <canvas
        ref={canvasRef}
        width={size}
        height={size}
        style={{
          width: `${size}px`,
          height: `${size}px`,
        }}
      />
    </div>
  );
}
