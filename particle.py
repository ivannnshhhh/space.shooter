from __future__ import annotations

import math
import random

import pygame


class Particle:
    def __init__(self, x, y, color, velocity, life, size=3):
        self.x = float(x)
        self.y = float(y)
        self.vx = float(velocity[0])
        self.vy = float(velocity[1])
        self.color = color
        self.life = float(life)
        self.max_life = float(life)
        self.size = size
        self.alpha = 255

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        self.alpha = int(max(0, 255 * (self.life / self.max_life)))
        self.vx *= 0.98
        self.vy *= 0.98

    def draw(self, surface):
        if self.life <= 0:
            return
        radius = max(1, int(self.size * (self.life / self.max_life + 0.2)))
        pygame.draw.circle(surface, self.color, (int(self.x), int(self.y)), radius)


class ParticleSystem:
    def __init__(self):
        self.particles = []

    def spawn_burst(self, x, y, color=(255, 255, 255), count=16, speed=180, spread=2.0, size=3):
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            velocity = (math.cos(angle) * random.uniform(speed * 0.3, speed) * spread,
                        math.sin(angle) * random.uniform(speed * 0.3, speed) * spread)
            life = random.uniform(0.4, 0.9)
            self.particles.append(Particle(x, y, color, velocity, life, size=size))

    def update(self, dt):
        for particle in list(self.particles):
            particle.update(dt)
            if particle.life <= 0:
                self.particles.remove(particle)

    def draw(self, surface):
        for particle in self.particles:
            particle.draw(surface)
