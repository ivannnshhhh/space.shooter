from __future__ import annotations

import math
import random

import pygame

import settings


class Enemy:
    def __init__(self, x, y, image_path, enemy_type="ufo", health=1, speed=120, score_value=10, entry_y=None):
        self.image = pygame.image.load(image_path).convert_alpha()
        self.image = pygame.transform.smoothscale(self.image, (80, 80))
        self.type = enemy_type
        self.health = health
        self.max_health = health
        self.x = float(x)
        self.base_x = float(x)
        self.base_y = max(settings.ENEMY_MIN_Y, min(float(y), settings.ENEMY_MAX_Y))
        self.y = float(entry_y) if entry_y is not None else self.base_y
        self.entering = entry_y is not None
        self.speed = speed
        self.base_speed = speed
        self.score_value = score_value
        self.hit_flash = 0.0
        self.fire_cooldown = random.uniform(0.6, 1.4)
        self.direction = random.choice([-1, 1])
        self.wave_phase = random.uniform(0, math.tau)
        self.vertical_amplitude = random.uniform(8, 18)
        self.attack_range = 850
        if self.type == "ship":
            self.fire_interval = random.uniform(1.15, 1.55)
            self.projectile_speed = settings.ENEMY_BULLET_SPEED * 1.12
            self.projectile_damage = settings.NORMAL_SHIP_BULLET_DAMAGE
        else:
            self.fire_interval = random.uniform(1.55, 2.0)
            self.projectile_speed = settings.ENEMY_BULLET_SPEED
            self.projectile_damage = settings.NORMAL_UFO_BULLET_DAMAGE
        self.rect = self.image.get_rect(center=(int(x), int(self.y)))
        self.alive = True

    def update(self, dt, player_x, player_y):
        if not self.alive:
            return
        self.hit_flash = max(0.0, self.hit_flash - dt * 5.0)
        self.fire_cooldown -= dt
        self.wave_phase += dt * 2.5
        if self.entering:
            self.y += (self.base_y - self.y) * min(1.0, dt * 5.0)
            if self.base_y - self.y < 2:
                self.y = self.base_y
                self.entering = False
            self.rect.center = (int(self.x), int(self.y))
            return
        self.x += self.direction * self.speed * dt
        min_x = settings.ENEMY_HORIZONTAL_MARGIN
        max_x = settings.GAME_WIDTH - settings.ENEMY_HORIZONTAL_MARGIN
        if self.x <= min_x or self.x >= max_x:
            self.x = max(min_x, min(self.x, max_x))
            self.direction *= -1
        self.y = self.base_y + math.sin(self.wave_phase) * self.vertical_amplitude
        self.y = max(settings.ENEMY_MIN_Y, min(self.y, settings.ENEMY_MAX_Y))
        self.rect.center = (int(self.x), int(self.y))

    def can_attack_player(self, player_x, player_y):
        return math.hypot(player_x - self.x, player_y - self.y) <= self.attack_range

    def begin_attack_cooldown(self):
        self.fire_cooldown = self.fire_interval

    def draw(self, surface):
        if not self.alive:
            return
        sprite = self.image.copy()
        if self.hit_flash > 0:
            white = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
            white.fill((255, 255, 255, int(120 * self.hit_flash)))
            sprite.blit(white, (0, 0))
        surface.blit(sprite, self.rect)

    def take_damage(self, amount):
        if not self.alive:
            return
        self.health -= amount
        self.hit_flash = 1.0
        if self.health <= 0:
            self.alive = False

    def draw_health_bar(self, surface):
        if not self.alive:
            return
        bar_width = max(30, self.rect.width)
        bg = pygame.Rect(self.rect.centerx - bar_width / 2, self.rect.top - 12, bar_width, 6)
        fill = pygame.Rect(bg.left, bg.top, max(0, bg.width * (self.health / self.max_health)), 6)
        pygame.draw.rect(surface, (60, 60, 80), bg, border_radius=3)
        pygame.draw.rect(surface, (124, 255, 157), fill, border_radius=3)
