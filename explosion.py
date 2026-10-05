from __future__ import annotations

import pygame

from particle import ParticleSystem
import settings


class Explosion:
    _sprite = None
    FRAME_COUNT = 12

    def __init__(self, x, y, scale=1.0, color=(255, 180, 60), particle_color=(255, 180, 80), life=0.62):
        self.x = float(x)
        self.y = float(y)
        self.scale = scale
        self.color = color
        self.life = life
        self.max_life = life
        if Explosion._sprite is None:
            try:
                Explosion._sprite = pygame.image.load(settings.asset_path("explosion.png")).convert_alpha()
            except (pygame.error, OSError):
                Explosion._sprite = False
        self.image = Explosion._sprite if Explosion._sprite is not False else None
        self.surf = None
        self._frame_index = -1
        self.particle_system = ParticleSystem()
        self.particle_system.spawn_burst(x, y, color=particle_color, count=max(8, int(18 * scale)), speed=220, spread=1.4, size=max(2, int(4 * scale)))

    def update(self, dt):
        self.life -= dt
        self.particle_system.update(dt)

    def draw(self, surface):
        if self.image is not None and self.life > 0:
            progress = min(1.0, max(0.0, 1.0 - self.life / self.max_life))
            frame_index = min(self.FRAME_COUNT - 1, int(progress * self.FRAME_COUNT))
            if frame_index != self._frame_index:
                grow = 0.72 + 0.32 * frame_index / (self.FRAME_COUNT - 1)
                size = max(1, int(150 * self.scale * grow))
                self.surf = pygame.transform.smoothscale(self.image, (size, size))
                self._frame_index = frame_index
            self.surf.set_alpha(int(255 * (1.0 - progress) ** 0.7))
            rect = self.surf.get_rect(center=(int(self.x), int(self.y)))
            surface.blit(self.surf, rect)
        self.particle_system.draw(surface)

    def finished(self):
        return self.life <= 0
