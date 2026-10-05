from __future__ import annotations

import pygame

import settings


class Player:
    def __init__(self, x, y, image_path):
        self.image = pygame.image.load(image_path).convert_alpha()
        self.image = pygame.transform.smoothscale(self.image, (78, 78))
        self.rect = self.image.get_rect(center=(x, y))
        self.x = float(x)
        self.y = float(y)
        self.speed = 380.0
        self.health = settings.PLAYER_MAX_HEALTH
        self.max_health = settings.PLAYER_MAX_HEALTH
        self.direction = 0.0
        self.hit_flash = 0.0
        self.damage_cooldown = 0.0
        self.fire_cooldown = 0.0
        self.shake = 0.0
        self.dead = False

    def update(self, dt, left_movement, right_movement):
        if self.dead:
            return
        target = 0.0
        if left_movement and not right_movement:
            target = -1.0
        elif right_movement and not left_movement:
            target = 1.0
        self.direction = target
        self.x += self.direction * self.speed * dt
        self.x = max(60, min(self.x, settings.GAME_WIDTH - 60))
        self.rect.centerx = int(self.x)
        self.rect.centery = int(self.y)
        self.hit_flash = max(0.0, self.hit_flash - dt * 3.0)
        self.damage_cooldown = max(0.0, self.damage_cooldown - dt)
        self.fire_cooldown = max(0.0, self.fire_cooldown - dt)

    def draw(self, surface):
        draw_surface = self.image.copy()
        if self.hit_flash > 0.0:
            white = pygame.Surface(draw_surface.get_size(), pygame.SRCALPHA)
            white.fill((255, 255, 255, int(120 * self.hit_flash)))
            draw_surface.blit(white, (0, 0))
        rect = draw_surface.get_rect(center=(int(self.x), int(self.y)))
        surface.blit(draw_surface, rect)

    def take_damage(self, amount):
        if self.dead:
            return
        self.health = max(0, self.health - amount)
        self.hit_flash = 1.0
        self.damage_cooldown = 0.2
        self.shake = 10
        if self.health <= 0:
            self.dead = True

    def heal(self, amount):
        self.health = min(self.max_health, self.health + amount)

    def draw_health_bar(self, surface, screen_x=140, screen_y=20):
        bar_width = 220
        bg = pygame.Rect(screen_x, screen_y, bar_width, 18)
        fill = pygame.Rect(screen_x, screen_y, int(bar_width * (self.health / self.max_health)), 18)
        pygame.draw.rect(surface, (32, 38, 55), bg, border_radius=10)
        pygame.draw.rect(surface, (66, 204, 255), fill, border_radius=10)
        label = pygame.font.SysFont("arial", 15, bold=True).render("PLAYER HP", True, (240, 250, 255))
        surface.blit(label, (screen_x, screen_y - 18))
