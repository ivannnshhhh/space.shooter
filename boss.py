from __future__ import annotations

import math

import pygame

import settings


class Boss:
    def __init__(self, x, y, image_path):
        self.image = pygame.image.load(image_path).convert_alpha()
        self.image = pygame.transform.smoothscale(self.image, (300, 210))
        self.x = float(x)
        self.y = float(y)
        self.base_x = float(x)
        self.rect = self.image.get_rect(center=(int(self.x), int(self.y)))
        self.health = 180
        self.max_health = 180
        self.speed = 150.0
        self.hit_flash = 0.0
        self.special_fire_cooldown = settings.BOSS_ATTACK_COOLDOWN
        self.phase_timer = 0.0
        self.alive = True
        self.active = False
        self.entering = True
        self.entry_y = -250

    def update(self, dt, player_x):
        if not self.alive:
            return
        self.phase_timer += dt
        self.hit_flash = max(0.0, self.hit_flash - dt * 5.0)
        self.special_fire_cooldown -= dt
        if self.entering:
            self.entry_y += 240 * dt
            self.y = min(self.entry_y, 150)
            if self.y >= 150:
                self.entering = False
                self.active = True
                self.special_fire_cooldown = settings.BOSS_ATTACK_COOLDOWN
        elif self.active:
            offset = math.sin(self.phase_timer * 1.6) * 160
            self.x = self.base_x + offset
            self.y = 150 + math.sin(self.phase_timer * 2.0) * 35
        self.rect.center = (int(self.x), int(self.y))

    def draw(self, surface):
        if not self.alive:
            return
        sprite = self.image.copy()
        if self.hit_flash > 0:
            white = pygame.Surface(sprite.get_size(), pygame.SRCALPHA)
            white.fill((255, 255, 255, int(150 * self.hit_flash)))
            sprite.blit(white, (0, 0))
        surface.blit(sprite, self.rect)

    def take_damage(self, amount):
        if not self.alive:
            return
        self.health -= amount
        self.hit_flash = 1.0
        if self.health <= 0:
            self.alive = False
            self.active = False

    def draw_health_bar(self, surface, x=150, y=25):
        if not self.alive:
            return
        bar_width = 320
        bg = pygame.Rect(x, y, bar_width, 18)
        fill = pygame.Rect(x, y, int(bar_width * (self.health / self.max_health)), 18)
        pygame.draw.rect(surface, (34, 22, 34), bg, border_radius=10)
        pygame.draw.rect(surface, (255, 77, 95), fill, border_radius=10)
        label = pygame.font.SysFont("arial", 16, bold=True).render("BOSS HP", True, (255, 245, 245))
        surface.blit(label, (x, y - 18))
