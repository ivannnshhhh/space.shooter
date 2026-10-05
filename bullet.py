from __future__ import annotations

import pygame

import settings


class Bullet:
    _image_cache = {}
    LASER_SIZE = (52, 78)
    HITBOX_SIZE = (20, 30)

    @classmethod
    def _load_sprite(cls, image_path):
        if image_path not in cls._image_cache:
            source = pygame.image.load(settings.asset_path(image_path)).convert_alpha()
            width = max(1, round(source.get_width() * cls.LASER_SIZE[1] / source.get_height()))
            cls._image_cache[image_path] = pygame.transform.smoothscale(source, (width, cls.LASER_SIZE[1]))
        return cls._image_cache[image_path]

    @classmethod
    def preload_sprites(cls):
        for image_path in ("lazer.png", "enmy_lazer.png"):
            try:
                cls._load_sprite(image_path)
            except (pygame.error, OSError):
                cls._image_cache[image_path] = None

    def __init__(self, x, y, vx=0.0, vy=-420, speed=420, color=(120, 230, 255), radius=5, enemy=False, damage=1, image_path=None):
        self.x = float(x)
        self.y = float(y)
        self.vx = float(vx)
        self.vy = float(vy)
        self.speed = float(speed)
        self.color = color
        self.radius = radius
        self.enemy = enemy
        self.owner = "enemy" if enemy else "player"
        self.direction = "down" if self.vy > 0 else "up"
        self.damage = damage
        self.life = 3.0
        self.rect = pygame.Rect(0, 0, radius * 2, radius * 2)
        self.image_rect = None
        self.alive = True

        self.image = None
        if image_path is not None:
            try:
                self.image = self._load_sprite(image_path)
                if self.image is not None:
                    self.rect = pygame.Rect(0, 0, *self.HITBOX_SIZE)
                    self.rect.center = (int(self.x), int(self.y))
                    self.image_rect = self.image.get_rect(center=self.rect.center)
            except (pygame.error, OSError):
                self.image = None

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.rect.center = (int(self.x), int(self.y))
        if self.image_rect is not None:
            self.image_rect.center = self.rect.center
        self.life -= dt
        if self.life <= 0:
            self.alive = False

    def draw(self, surface):
        if not self.alive or self.image is None:
            return
        surface.blit(self.image, self.image_rect)
