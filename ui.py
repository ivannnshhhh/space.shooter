from __future__ import annotations

import pygame


class Button:
    def __init__(self, x, y, width, height, text, fg=(255, 255, 255), bg=(44, 62, 80), accent=(0, 255, 255), font=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.fg = fg
        self.bg = bg
        self.accent = accent
        self.font = font
        self.hovered = False

    def draw(self, surface):
        if self.hovered:
            color = self.accent
            border = (255, 255, 255)
        else:
            color = self.bg
            border = self.accent
        pygame.draw.rect(surface, color, self.rect, border_radius=16)
        pygame.draw.rect(surface, border, self.rect, 3, border_radius=16)
        if self.font is not None:
            label = self.font.render(self.text, True, self.fg)
            label_rect = label.get_rect(center=self.rect.center)
            surface.blit(label, label_rect)

    def handle_mouse(self, pos):
        self.hovered = self.rect.collidepoint(pos)

    def is_clicked(self, pos):
        return self.rect.collidepoint(pos)


class UiPanel:
    def __init__(self, x, y, w, h, title="", bg=(12, 18, 30), alpha=180):
        self.rect = pygame.Rect(x, y, w, h)
        self.title = title
        self.bg = bg
        self.alpha = alpha

    def draw(self, surface):
        overlay = pygame.Surface((self.rect.width, self.rect.height), pygame.SRCALPHA)
        pygame.draw.rect(overlay, (*self.bg, self.alpha), overlay.get_rect(), border_radius=16)
        pygame.draw.rect(overlay, (120, 140, 170, 120), overlay.get_rect(), 1, border_radius=16)
        surface.blit(overlay, self.rect.topleft)

        if self.title:
            title_surf = pygame.font.SysFont("arial", 16, bold=True).render(self.title, True, (200, 220, 255))
            surface.blit(title_surf, (self.rect.left + 12, self.rect.top + 10))
