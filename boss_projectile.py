from __future__ import annotations

import math

import pygame

import settings


class BossProjectile:
    _image = None
    DISPLAY_SIZE = 36
    HITBOX_SIZE = 28

    @classmethod
    def preload(cls):
        if cls._image is None:
            source = pygame.image.load(settings.asset_path("boss_enemy_bullet.png")).convert_alpha()
            cls._image = pygame.transform.smoothscale(source, (cls.DISPLAY_SIZE, cls.DISPLAY_SIZE))

    def __init__(self, damage):
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.direction = pygame.Vector2()
        self.damage = damage
        self.owner = "boss"
        self.life = 8.0
        self.alive = True
        self.image = self._image
        self.rect = pygame.Rect(0, 0, self.HITBOX_SIZE, self.HITBOX_SIZE)

    def draw(self, surface):
        if self.alive and self.image is not None:
            surface.blit(self.image, self.image.get_rect(center=self.rect.center))


class BossProjectileVolley:
    def __init__(self, x, y, target_x, target_y):
        self.x = float(x)
        self.y = float(y)
        self.target_x = float(target_x)
        self.target_y = float(target_y)
        self.speed = settings.BOSS_SPREAD_BULLET_SPEED
        self.elapsed = 0.0
        self.direction = pygame.Vector2(target_x - x, target_y - y)
        if self.direction.length_squared() == 0:
            self.direction.update(0, 1)
        else:
            self.direction = self.direction.normalize()
        self.perpendicular = pygame.Vector2(-self.direction.y, self.direction.x)
        self.projectiles = [BossProjectile(settings.BOSS_BULLET_DAMAGE) for _ in range(3)]
        for projectile, offset in zip(self.projectiles, (-1, 0, 1)):
            projectile.direction = self.direction.copy()
            projectile.vx = self.direction.x * self.speed
            projectile.vy = self.direction.y * self.speed
            projectile.x = self.x + self.perpendicular.x * settings.BOSS_SPREAD_BASE_SPACING * offset
            projectile.y = self.y + self.perpendicular.y * settings.BOSS_SPREAD_BASE_SPACING * offset
            projectile.rect.center = (round(projectile.x), round(projectile.y))

    @property
    def alive(self):
        return any(projectile.alive for projectile in self.projectiles)

    def update(self, dt):
        self.elapsed += dt
        self.x += self.direction.x * self.speed * dt
        self.y += self.direction.y * self.speed * dt
        phase = math.tau * self.elapsed / settings.BOSS_SPREAD_OSCILLATION_PERIOD
        oscillation = 0.5 + 0.5 * math.cos(phase)
        spacing = settings.BOSS_SPREAD_MIN_SPACING + (
            settings.BOSS_SPREAD_BASE_SPACING - settings.BOSS_SPREAD_MIN_SPACING
        ) * oscillation

        for index, projectile in enumerate(self.projectiles):
            if not projectile.alive:
                continue
            lateral_offset = (index - 1) * spacing
            projectile.x = self.x + self.perpendicular.x * lateral_offset
            projectile.y = self.y + self.perpendicular.y * lateral_offset
            projectile.rect.center = (round(projectile.x), round(projectile.y))
            projectile.life -= dt
            if (
                projectile.life <= 0
                or projectile.rect.bottom < 0
                or projectile.rect.top > settings.GAME_HEIGHT
                or projectile.rect.right < 0
                or projectile.rect.left > settings.GAME_WIDTH
            ):
                projectile.alive = False