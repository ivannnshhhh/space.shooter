from __future__ import annotations

import random
import threading

import cv2
import pygame

import boss
import bullet
import camera
import enemy
import explosion
import hand_tracking
import boss_projectile
import particle
import player
import settings
import ui


class Game:
    def __init__(self):
        pygame.display.init()
        pygame.font.init()
        self.window = pygame.display.set_mode(
            (settings.DEFAULT_WINDOW_WIDTH, settings.DEFAULT_WINDOW_HEIGHT),
            pygame.RESIZABLE,
        )
        bullet.Bullet.preload_sprites()
        boss_projectile.BossProjectile.preload()
        self.screen = pygame.Surface((settings.GAME_WIDTH, settings.GAME_HEIGHT))
        self.viewport_rect = self.window.get_rect()
        pygame.display.set_caption(settings.TITLE)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 22, bold=True)
        self.big_font = pygame.font.SysFont("arial", 48, bold=True)
        self.small_font = pygame.font.SysFont("arial", 18)
        self.state = "MAIN_MENU"

        try:
            self.background_source = pygame.image.load(settings.asset_path("space_background.png")).convert()
        except Exception as exc:  # pragma: no cover
            print(f"Missing asset: {exc}")
            self.background_source = pygame.Surface((settings.GAME_WIDTH, settings.GAME_HEIGHT))
            self.background_source.fill((8, 12, 24))
        self.background = self._cover_surface(self.background_source, (settings.GAME_WIDTH, settings.GAME_HEIGHT))
        self.window_background = None
        self.window_background_size = None

        self.star_particles = []
        for _ in range(80):
            self.star_particles.append({
                "x": random.randint(0, settings.GAME_WIDTH),
                "y": random.randint(0, settings.GAME_HEIGHT),
                "speed": random.uniform(20, 80),
                "radius": random.uniform(1, 3),
            })

        self.camera_manager = None
        self.hand_tracker = None
        self.camera_surface = pygame.Surface((settings.CAMERA_PREVIEW_WIDTH, settings.CAMERA_PREVIEW_HEIGHT))
        self.camera_surface.fill((5, 10, 18))
        self.camera_preview_surface = None
        self.camera_status = "Initializing camera..."
        self._camera_lock = threading.Lock()
        self._camera_stop = threading.Event()
        self._camera_thread = None
        self._camera_started = False
        self._camera_controls_enabled = False
        self._latest_camera_frame = None
        self._latest_frame_id = 0
        self._displayed_frame_id = 0
        self._latest_hands = []

        self.player = player.Player(settings.PLAYER_START_X, settings.PLAYER_START_Y, settings.asset_path("spaceship.png"))
        self.enemies = []
        self.bullets = []
        self.enemy_bullets = []
        self.boss_projectile_volleys = []
        self.explosions = []
        self.particle_system = particle.ParticleSystem()
        self.boss = None
        self.score = 0
        self.wave_total = 0
        self.wave_remaining = 0
        self.enemies_defeated = 0
        self.enemies_spawned_count = 0
        self.last_spawn_trigger_kill_count = 0
        self.pending_enemy_spawns = []
        self.spawn_entry_timer = 0.0
        self.boss_warning_timer = 0.0
        self.player_explosion_timer = 0.0
        self.boss_explosion_timer = 0.0
        self.menu_button_cooldown = 0.0
        self.screen_shake = 0.0
        self.explosion_sound = None
        self.laser_sound = None
        self.game_over_sound = None
        self.explosion_channels = []
        self.laser_channels = []
        self.game_over_channel = None
        self._explosion_channel_cursor = 0
        self._laser_channel_cursor = 0
        self._audio_loaded = False
        self._music_target_volume = settings.MENU_MUSIC_VOLUME

        self.play_button = ui.Button(430, 430, 200, 60, "PLAY", font=self.font)
        self.tutorial_button = ui.Button(570, 430, 220, 60, "TUTORIAL", font=self.font)
        self.back_button = ui.Button(500, 620, 200, 60, "BACK", font=self.font)
        self.retry_button = ui.Button(390, 500, 200, 60, "RETRY", font=self.font)
        self.main_menu_button = ui.Button(610, 500, 220, 60, "MAIN MENU", font=self.font)

    def load_audio(self):
        if self._audio_loaded:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.set_num_channels(settings.MIXER_CHANNEL_COUNT)
            pygame.mixer.set_reserved(settings.RESERVED_AUDIO_CHANNELS)
            self.explosion_channels = [
                pygame.mixer.Channel(index)
                for index in range(settings.MAX_EXPLOSION_CHANNELS)
            ]
            laser_start = settings.MAX_EXPLOSION_CHANNELS
            self.laser_channels = [
                pygame.mixer.Channel(index)
                for index in range(laser_start, laser_start + settings.MAX_LASER_CHANNELS)
            ]
            self.game_over_channel = pygame.mixer.Channel(settings.GAME_OVER_CHANNEL_INDEX)
            pygame.mixer.music.load(settings.asset_path("background_music.mp3"))
            pygame.mixer.music.set_volume(settings.MENU_MUSIC_VOLUME)
            pygame.mixer.music.play(-1)
            self.explosion_sound = pygame.mixer.Sound(settings.asset_path("sound_explosion.mp3"))
            self.explosion_sound.set_volume(settings.EXPLOSION_VOLUME)
            self.laser_sound = pygame.mixer.Sound(settings.asset_path("sound_laser.mp3"))
            self.laser_sound.set_volume(settings.LASER_VOLUME)
            self.game_over_sound = pygame.mixer.Sound(settings.asset_path("gameover.mp3"))
            self.game_over_sound.set_volume(settings.GAME_OVER_SOUND_VOLUME)
            self._music_target_volume = settings.MENU_MUSIC_VOLUME
            self._audio_loaded = True
        except Exception as exc:  # pragma: no cover
            print(f"Audio unavailable: {exc}")

    def _play_on_free_channel(self, sound, channels, cursor_attribute):
        if sound is None or not channels:
            return False
        start = getattr(self, cursor_attribute)
        for offset in range(len(channels)):
            index = (start + offset) % len(channels)
            channel = channels[index]
            if not channel.get_busy():
                channel.set_volume(1.0)
                channel.play(sound)
                setattr(self, cursor_attribute, (index + 1) % len(channels))
                return True
        return False

    def _play_explosion_sound(self):
        return self._play_on_free_channel(
            self.explosion_sound,
            self.explosion_channels,
            "_explosion_channel_cursor",
        )

    def _play_laser_sound(self):
        return self._play_on_free_channel(
            self.laser_sound,
            self.laser_channels,
            "_laser_channel_cursor",
        )

    def _play_game_over_sound(self):
        if self.game_over_sound is not None and self.game_over_channel is not None:
            self.game_over_channel.set_volume(1.0)
            self.game_over_channel.play(self.game_over_sound)

    def _stop_game_over_sound(self):
        if self.game_over_channel is not None:
            self.game_over_channel.stop()

    def _stop_laser_sounds(self):
        for channel in self.laser_channels:
            channel.stop()

    def _update_audio(self, dt):
        if not self._audio_loaded:
            return
        if self.state in {"MAIN_MENU", "TUTORIAL"}:
            target_volume = settings.MENU_MUSIC_VOLUME
        elif self.state in {"PLAYER_EXPLODING", "GAME_OVER"}:
            target_volume = settings.GAME_OVER_MUSIC_VOLUME
        else:
            target_volume = settings.GAMEPLAY_MUSIC_VOLUME

        self._music_target_volume = target_volume
        current_volume = pygame.mixer.music.get_volume()
        difference = target_volume - current_volume
        step = settings.MUSIC_VOLUME_FADE_RATE * dt
        if abs(difference) <= step:
            next_volume = target_volume
        else:
            next_volume = current_volume + (step if difference > 0 else -step)
        pygame.mixer.music.set_volume(next_volume)

    def _start_game(self):
        self._stop_game_over_sound()
        self._stop_laser_sounds()
        self._reset_wave()
        self.state = "PLAYING"

    def _reset_wave(self):
        self._clear_gameplay_state()
        self.spawn_enemies()

    def _clear_gameplay_state(self):
        self.player = player.Player(settings.PLAYER_START_X, settings.PLAYER_START_Y, settings.asset_path("spaceship.png"))
        self.enemies.clear()
        self.bullets.clear()
        self.enemy_bullets.clear()
        self.boss_projectile_volleys.clear()
        self.explosions.clear()
        self.particle_system = particle.ParticleSystem()
        self.score = 0
        self.enemies_defeated = 0
        self.enemies_spawned_count = 0
        self.last_spawn_trigger_kill_count = 0
        self.pending_enemy_spawns.clear()
        self.spawn_entry_timer = 0.0
        self.wave_total = 0
        self.wave_remaining = 0
        self.boss = None
        self.boss_warning_timer = 0.0
        self.player_explosion_timer = 0.0
        self.boss_explosion_timer = 0.0
        self.screen_shake = 0.0

    def spawn_enemies(self, group_size=None):
        remaining_to_spawn = settings.NORMAL_ENEMY_TARGET - self.enemies_spawned_count
        if remaining_to_spawn <= 0 or self.enemies_defeated >= settings.NORMAL_ENEMY_TARGET:
            return 0

        requested_size = random.randint(3, 5) if group_size is None else group_size
        group_count = min(requested_size, remaining_to_spawn)
        slots = random.sample(range(6), group_count)
        self.wave_total = group_count
        for i in range(group_count):
            ship_type = "ufo" if i % 2 == 0 else "ship"
            image_name = "enmy_UFO.png" if ship_type == "ufo" else "enmy_spaceship.png"
            column = slots[i]
            x = 120 + column * (settings.GAME_WIDTH - 240) / 5
            x += random.randint(-14, 14)
            y = settings.ENEMY_MIN_Y + 20 + (i // 6) * 90
            health = settings.NORMAL_UFO_HEALTH if ship_type == "ufo" else settings.NORMAL_SHIP_HEALTH
            speed = random.uniform(70, 120)
            score_value = 15 if ship_type == "ufo" else 20
            actor = enemy.Enemy(
                x,
                y,
                settings.asset_path(image_name),
                ship_type,
                health,
                speed,
                score_value,
                entry_y=-45,
            )
            self.pending_enemy_spawns.append(actor)
            self.enemies_spawned_count += 1

        self.wave_remaining = len(self.enemies) + len(self.pending_enemy_spawns)
        return group_count

    def _update_spawn_queue(self, dt):
        self.spawn_entry_timer = max(0.0, self.spawn_entry_timer - dt)
        if self.pending_enemy_spawns and self.spawn_entry_timer <= 0:
            self.enemies.append(self.pending_enemy_spawns.pop(0))
            self.spawn_entry_timer = 0.32
        self.wave_remaining = len(self.enemies) + len(self.pending_enemy_spawns)

    def _get_hand_state(self):
        with self._camera_lock:
            frame_id = self._latest_frame_id
            frame = None
            if frame_id != self._displayed_frame_id and self._latest_camera_frame is not None:
                frame = self._latest_camera_frame.copy()
            hands = list(self._latest_hands)
        if frame is not None and frame.size:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.camera_surface = pygame.image.frombuffer(
                rgb.tobytes(), (frame.shape[1], frame.shape[0]), "RGB"
            ).copy()
            self.camera_preview_surface = None
            self._displayed_frame_id = frame_id
        return hands if self._camera_controls_enabled else []

    def _camera_tracking_worker(self):
        camera_manager = None
        hand_tracker = None
        try:
            camera_manager = camera.CameraManager()
            with self._camera_lock:
                self.camera_manager = camera_manager

            while not self._camera_stop.is_set() and not camera_manager.is_available():
                with self._camera_lock:
                    self.camera_status = camera_manager.camera_error or "Webcam unavailable"
                    self._camera_controls_enabled = False
                self._camera_stop.wait(0.1)

            if self._camera_stop.is_set():
                return

            with self._camera_lock:
                self.camera_status = "Camera ready; initializing hand tracking..."
            hand_tracker = hand_tracking.HandTracker()
            with self._camera_lock:
                self.hand_tracker = hand_tracker
                self._camera_controls_enabled = hand_tracker.hands is not None
                self.camera_status = "Camera ready" if self._camera_controls_enabled else "Camera ready; hand tracking unavailable"

            while not self._camera_stop.is_set():
                if not camera_manager.is_available():
                    with self._camera_lock:
                        self.camera_status = camera_manager.camera_error or "Webcam unavailable"
                        self._camera_controls_enabled = False
                        self._latest_camera_frame = None
                        self._latest_hands = []
                    self._camera_stop.wait(0.1)
                    continue

                frame = camera_manager.read_frame()
                if frame is None:
                    self._camera_stop.wait(0.03)
                    continue

                try:
                    info = hand_tracker.process_frame(frame)
                except Exception as exc:
                    with self._camera_lock:
                        self.camera_status = f"Hand tracking unavailable: {exc}"
                        self._camera_controls_enabled = False
                    self._camera_stop.wait(0.03)
                    continue

                with self._camera_lock:
                    self._latest_camera_frame = info["debug_frame"]
                    self._latest_frame_id += 1
                    self._latest_hands = info["hands"]
                    self.camera_status = "Camera ready" if hand_tracker.hands is not None else hand_tracker.error_message
                    self._camera_controls_enabled = hand_tracker.hands is not None
        except Exception as exc:
            with self._camera_lock:
                self.camera_status = f"Camera unavailable: {exc}"
                self._camera_controls_enabled = False
        finally:
            if camera_manager is not None:
                camera_manager.close()
            if hand_tracker is not None:
                hand_tracker.close()

    def _start_camera_worker(self):
        if self._camera_started:
            return
        self._camera_started = True
        self._camera_thread = threading.Thread(target=self._camera_tracking_worker, daemon=True)
        self._camera_thread.start()

    def _find_hand(self, hands, label):
        for hand in hands:
            if hand.label == label:
                return hand
        return None

    def update_menu(self, dt, hands):
        self.menu_button_cooldown = max(0.0, self.menu_button_cooldown - dt)
        left = self._find_hand(hands, "LEFT")
        right = self._find_hand(hands, "RIGHT")
        if right and right.trigger_play and self.menu_button_cooldown <= 0:
            self._start_game()
            self.menu_button_cooldown = 0.8
        elif left and left.trigger_tutorial and self.menu_button_cooldown <= 0:
            self.state = "TUTORIAL"
            self.menu_button_cooldown = 0.8

    def update_tutorial(self, dt, hands):
        self.menu_button_cooldown = max(0.0, self.menu_button_cooldown - dt)
        left = self._find_hand(hands, "LEFT")
        right = self._find_hand(hands, "RIGHT")
        if left and left.trigger_tutorial and self.menu_button_cooldown <= 0:
            self.state = "MAIN_MENU"
            self.menu_button_cooldown = 0.5
        if right and right.trigger_play and self.menu_button_cooldown <= 0:
            self._start_game()
            self.menu_button_cooldown = 0.8

    def update_game_over(self, dt, hands):
        self.menu_button_cooldown = max(0.0, self.menu_button_cooldown - dt)
        left_hand = self._find_hand(hands, "LEFT")
        right_hand = self._find_hand(hands, "RIGHT")
        if left_hand and left_hand.trigger_tutorial and self.menu_button_cooldown <= 0:
            self._start_game()
            self.menu_button_cooldown = 0.8
        elif right_hand and right_hand.trigger_play and self.menu_button_cooldown <= 0:
            self._stop_game_over_sound()
            self._stop_laser_sounds()
            self._clear_gameplay_state()
            self.state = "MAIN_MENU"
            self.menu_button_cooldown = 0.8

    def update_playing(self, dt, hands):
        if self.state not in {"PLAYING", "BOSS_INCOMING", "BOSS_FIGHT"}:
            return

        left_h = self._find_hand(hands, "LEFT")
        right_h = self._find_hand(hands, "RIGHT")
        left_move = bool(right_h and (right_h.move_left or right_h.move_right))
        right_move = bool(left_h and (left_h.move_left or left_h.move_right))
        self.player.update(dt, left_move, right_move)

        if self.state == "BOSS_INCOMING":
            self.boss_warning_timer = max(0.0, self.boss_warning_timer - dt)
            if self.boss_warning_timer <= 0:
                self.boss = boss.Boss(settings.GAME_WIDTH / 2, -200, settings.asset_path("boss_enemy.png"))
                self.state = "BOSS_FIGHT"

        if self.state == "PLAYING":
            self._update_spawn_queue(dt)
            for enemy_obj in self.enemies:
                if not enemy_obj.alive:
                    continue
                enemy_obj.update(dt, self.player.x, self.player.y)
                if (
                    not enemy_obj.entering
                    and
                    not self.player.dead
                    and enemy_obj.fire_cooldown <= 0
                    and enemy_obj.can_attack_player(self.player.x, self.player.y)
                ):
                    enemy_obj.begin_attack_cooldown()
                    self.enemy_bullets.append(
                        bullet.Bullet(
                            enemy_obj.x,
                            enemy_obj.y + 20,
                            vx=0,
                            vy=enemy_obj.projectile_speed,
                            speed=enemy_obj.projectile_speed,
                            color=(255, 120, 120),
                            radius=6,
                            enemy=True,
                            damage=enemy_obj.projectile_damage,
                            image_path="enmy_lazer.png",
                        )
                    )

            targets = [enemy_obj for enemy_obj in self.enemies if enemy_obj.alive and not enemy_obj.entering]
            if targets:
                target = min(targets, key=lambda item: (item.x - self.player.x) ** 2 + (item.y - self.player.y) ** 2)
                self._fire_player_at(target)

        if self.state == "BOSS_FIGHT" and self.boss is not None and self.boss.alive:
            self.boss.update(dt, self.player.x)
            if (
                self.boss.active
                and self.boss.special_fire_cooldown <= 0
                and len(self.boss_projectile_volleys) < settings.BOSS_SPREAD_MAX_ACTIVE_VOLLEYS
            ):
                self.boss.special_fire_cooldown = settings.BOSS_ATTACK_COOLDOWN
                self.boss_projectile_volleys.append(
                    boss_projectile.BossProjectileVolley(
                        self.boss.rect.centerx,
                        self.boss.rect.bottom - 12,
                        self.player.x,
                        self.player.y,
                    )
                )
            if not self.player.dead:
                self._fire_player_at(self.boss)

        self._update_projectiles(dt)
        self._check_collisions()
        if self.state == "PLAYING":
            if self.enemies_defeated >= settings.NORMAL_ENEMY_TARGET:
                self._begin_boss_sequence()
            elif self.enemies_defeated >= self.last_spawn_trigger_kill_count + 3:
                self.last_spawn_trigger_kill_count = (self.enemies_defeated // 3) * 3
                self.spawn_enemies()

    def _fire_player_at(self, target):
        if self.player.fire_cooldown > 0 or self.player.dead or not target.alive:
            return
        self.player.fire_cooldown = 0.18
        self.bullets.append(
            bullet.Bullet(
                self.player.x,
                self.player.y - 28,
                vx=0,
                vy=-settings.BULLET_SPEED,
                speed=settings.BULLET_SPEED,
                color=(120, 230, 255),
                radius=6,
                damage=1,
                image_path="lazer.png",
            )
        )
        self._play_laser_sound()

    def _begin_boss_sequence(self):
        self.enemies.clear()
        self.pending_enemy_spawns.clear()
        self.enemy_bullets.clear()
        self.bullets.clear()
        self.boss = None
        self.boss_warning_timer = 2.0
        self.state = "BOSS_INCOMING"
        self.screen_shake = max(self.screen_shake, 9.0)

    def _update_projectiles(self, dt):
        for bullet_obj in self.bullets[:]:
            bullet_obj.update(dt)
            if (
                not bullet_obj.alive
                or bullet_obj.rect.bottom < 0
                or bullet_obj.rect.right < 0
                or bullet_obj.rect.left > settings.GAME_WIDTH
            ):
                self.bullets.remove(bullet_obj)

        for bullet_obj in self.enemy_bullets[:]:
            bullet_obj.update(dt)
            if (
                not bullet_obj.alive
                or bullet_obj.rect.top > settings.GAME_HEIGHT
                or bullet_obj.rect.right < 0
                or bullet_obj.rect.left > settings.GAME_WIDTH
            ):
                self.enemy_bullets.remove(bullet_obj)

        for volley in self.boss_projectile_volleys[:]:
            volley.update(dt)
            if not volley.alive:
                self.boss_projectile_volleys.remove(volley)

        self._update_effects(dt)

    def _update_effects(self, dt):
        for explosion_obj in self.explosions[:]:
            explosion_obj.update(dt)
            if explosion_obj.finished():
                self.explosions.remove(explosion_obj)
        self.particle_system.update(dt)

    def _update_transition_effects(self, dt):
        self._update_effects(dt)
        if self.state == "PLAYER_EXPLODING":
            self.player_explosion_timer = max(0.0, self.player_explosion_timer - dt)
            if self.player_explosion_timer <= 0:
                self.state = "GAME_OVER"
                self._play_game_over_sound()
        elif self.state == "BOSS_EXPLODING":
            self.boss_explosion_timer = max(0.0, self.boss_explosion_timer - dt)
            if self.boss_explosion_timer <= 0:
                self.state = "VICTORY"

    def _check_collisions(self):
        for bullet_obj in self.bullets[:]:
            for enemy_obj in self.enemies[:]:
                if enemy_obj.alive and enemy_obj.rect.colliderect(bullet_obj.rect):
                    enemy_obj.take_damage(bullet_obj.damage)
                    self.particle_system.spawn_burst(bullet_obj.x, bullet_obj.y, color=(120, 230, 255), count=8, speed=180, spread=1.5, size=3)
                    if bullet_obj in self.bullets:
                        self.bullets.remove(bullet_obj)
                    if not enemy_obj.alive:
                        self._record_enemy_destroyed(enemy_obj)
                    break

            if bullet_obj not in self.bullets:
                continue
            if self.boss is not None and self.boss.alive and self.boss.rect.colliderect(bullet_obj.rect):
                self.boss.take_damage(bullet_obj.damage)
                self.particle_system.spawn_burst(bullet_obj.x, bullet_obj.y, color=(255, 130, 120), count=10, speed=220, spread=1.3, size=4)
                self.bullets.remove(bullet_obj)
                if not self.boss.alive:
                    self.score += 500
                    self._trigger_victory()
                break

        for bullet_obj in self.enemy_bullets[:]:
            if self.player.rect.colliderect(bullet_obj.rect):
                if self.player.damage_cooldown <= 0:
                    self.player.take_damage(bullet_obj.damage)
                    self.particle_system.spawn_burst(bullet_obj.x, bullet_obj.y, color=(255, 100, 100), count=12, speed=200, spread=1.5, size=4)
                    self.screen_shake = max(self.screen_shake, 5.0)
                self.enemy_bullets.remove(bullet_obj)
                if self.player.dead:
                    self._trigger_game_over()
                    break

        for volley in self.boss_projectile_volleys[:]:
            for projectile in volley.projectiles:
                if projectile.alive and self.player.rect.colliderect(projectile.rect):
                    if self.player.damage_cooldown <= 0:
                        self.player.take_damage(projectile.damage)
                        self.particle_system.spawn_burst(
                            projectile.x,
                            projectile.y,
                            color=(255, 125, 100),
                            count=12,
                            speed=200,
                            spread=1.5,
                            size=4,
                        )
                        self.screen_shake = max(self.screen_shake, 5.0)
                    projectile.alive = False
                    if self.player.dead:
                        self._trigger_game_over()
                        break
            if not volley.alive and volley in self.boss_projectile_volleys:
                self.boss_projectile_volleys.remove(volley)
            if self.player.dead:
                break

        for enemy_obj in self.enemies[:]:
            if self.player.rect.colliderect(enemy_obj.rect.inflate(16, 16)):
                if self.player.damage_cooldown <= 0:
                    self.player.take_damage(25)
                enemy_obj.take_damage(enemy_obj.health)
                self._record_enemy_destroyed(enemy_obj)
                if self.player.dead:
                    self._trigger_game_over()
                    break

        if self.boss is not None and self.boss.alive and self.player.rect.colliderect(self.boss.rect.inflate(-20, -20)):
            if self.player.damage_cooldown <= 0:
                self.player.take_damage(15)
            if self.player.dead:
                self._trigger_game_over()

    def _record_enemy_destroyed(self, enemy_obj):
        if enemy_obj in self.enemies:
            self.enemies.remove(enemy_obj)
            self.enemies_defeated = min(settings.NORMAL_ENEMY_TARGET, self.enemies_defeated + 1)
            self.wave_remaining = len(self.enemies) + len(self.pending_enemy_spawns)
            self.score += enemy_obj.score_value
            self.explosions.append(explosion.Explosion(
                enemy_obj.x,
                enemy_obj.y,
                scale=0.9,
                particle_color=(255, 200, 100),
                life=0.58,
            ))
            self.particle_system.spawn_burst(enemy_obj.x, enemy_obj.y, color=(255, 190, 95), count=16, speed=190, spread=1.3, size=3)
            self.screen_shake = max(self.screen_shake, 1.5)
            self._play_explosion_sound()

    def _trigger_game_over(self):
        if self.state in {"PLAYER_EXPLODING", "GAME_OVER"}:
            return
        self.player.dead = True
        self.state = "PLAYER_EXPLODING"
        self.player_explosion_timer = 0.72
        self._stop_laser_sounds()
        self.bullets.clear()
        self.enemy_bullets.clear()
        self.boss_projectile_volleys.clear()
        self.explosions.append(explosion.Explosion(
            self.player.x,
            self.player.y,
            scale=1.55,
            particle_color=(255, 100, 100),
            life=0.7,
        ))
        self.particle_system.spawn_burst(self.player.x, self.player.y, color=(255, 115, 90), count=30, speed=250, spread=1.4, size=4)
        self.screen_shake = max(self.screen_shake, 10.0)
        self._play_explosion_sound()

    def _trigger_victory(self):
        if self.state in {"BOSS_EXPLODING", "VICTORY"}:
            return
        self.state = "BOSS_EXPLODING"
        self.boss_explosion_timer = 0.9
        self.enemy_bullets.clear()
        self.bullets.clear()
        self.boss_projectile_volleys.clear()
        if self.boss is not None:
            self.explosions.append(explosion.Explosion(
                self.boss.x,
                self.boss.y,
                scale=3.1,
                particle_color=(255, 190, 95),
                life=0.82,
            ))
            for _ in range(5):
                self.explosions.append(explosion.Explosion(
                    self.boss.x + random.randint(-100, 100),
                    self.boss.y + random.randint(-55, 55),
                    scale=0.8,
                    particle_color=(255, 200, 100),
                    life=0.58,
                ))
            self.particle_system.spawn_burst(self.boss.x, self.boss.y, color=(255, 185, 90), count=70, speed=300, spread=1.6, size=5)
        self.screen_shake = max(self.screen_shake, 30.0)
        self._play_explosion_sound()

    @staticmethod
    def _cover_surface(source, target_size):
        target_width, target_height = target_size
        scale = max(target_width / source.get_width(), target_height / source.get_height())
        scaled_size = (
            max(target_width, int(round(source.get_width() * scale))),
            max(target_height, int(round(source.get_height() * scale))),
        )
        scaled = pygame.transform.smoothscale(source, scaled_size)
        crop = pygame.Rect(0, 0, target_width, target_height)
        crop.center = scaled.get_rect().center
        return scaled.subsurface(crop).copy()

    def draw_background(self, dt):
        self.screen.fill((6, 9, 20))
        self.screen.blit(self.background, (0, 0))
        for star in self.star_particles:
            star["y"] = (star["y"] + star["speed"] * dt) % settings.GAME_HEIGHT
            pygame.draw.circle(self.screen, (255, 255, 255), (int(star["x"]), int(star["y"])), int(star["radius"]))

    def draw_gameplay(self):
        if not self.player.dead:
            self.player.draw(self.screen)
        for enemy_obj in self.enemies:
            enemy_obj.draw(self.screen)
            enemy_obj.draw_health_bar(self.screen)
        if self.boss is not None and self.boss.alive:
            self.boss.draw(self.screen)
        for bullet_obj in self.bullets:
            bullet_obj.draw(self.screen)
        for bullet_obj in self.enemy_bullets:
            bullet_obj.draw(self.screen)
        for volley in self.boss_projectile_volleys:
            for projectile in volley.projectiles:
                projectile.draw(self.screen)
        for explosion_obj in self.explosions:
            explosion_obj.draw(self.screen)
        self.particle_system.draw(self.screen)
        self.draw_hud()

    def draw_hud(self):
        left = 32
        bar_y = 48
        player_label = self.small_font.render("PLAYER HP", True, (235, 245, 255))
        self.screen.blit(player_label, (left, 22))
        pygame.draw.rect(self.screen, (27, 35, 48), (left, bar_y, 250, 16), border_radius=6)
        player_width = int(250 * self.player.health / self.player.max_health)
        pygame.draw.rect(self.screen, (66, 204, 255), (left, bar_y, player_width, 16), border_radius=6)

        score = self.font.render(f"SCORE: {self.score}", True, (255, 255, 255))
        self.screen.blit(score, score.get_rect(topright=(settings.GAME_WIDTH - 32, 25)))
        self.draw_enemy_progress_bar()

        if self.boss is not None and self.boss.alive:
            bar_width = 420
            bar_x = (settings.GAME_WIDTH - bar_width) // 2
            label = self.small_font.render("BOSS HP", True, (255, 230, 230))
            self.screen.blit(label, label.get_rect(center=(settings.GAME_WIDTH // 2, 82)))
            pygame.draw.rect(self.screen, (45, 26, 35), (bar_x, 94, bar_width, 17), border_radius=7)
            fill_width = int(bar_width * max(0, self.boss.health) / self.boss.max_health)
            pygame.draw.rect(self.screen, (244, 76, 94), (bar_x, 94, fill_width, 17), border_radius=7)

    def draw_enemy_progress_bar(self):
        bar_width = 340
        x = (settings.GAME_WIDTH - bar_width) // 2
        label = self.small_font.render("ENEMIES DEFEATED", True, (225, 235, 245))
        self.screen.blit(label, (x, 22))
        pygame.draw.rect(self.screen, (24, 32, 40), (x, 48, bar_width, 16), border_radius=6)
        progress = min(1.0, self.enemies_defeated / settings.NORMAL_ENEMY_TARGET)
        fill_width = int(progress * bar_width)
        if fill_width > 0:
            pygame.draw.rect(self.screen, (112, 225, 155), (x, 48, fill_width, 16), border_radius=6)
        count = self.small_font.render(
            f"{self.enemies_defeated} / {settings.NORMAL_ENEMY_TARGET}",
            True,
            (255, 255, 255),
        )
        self.screen.blit(count, (x + bar_width + 12, 45))

    def draw_camera_preview(self):
        panel = pygame.Rect(20, settings.GAME_HEIGHT - settings.CAMERA_PREVIEW_HEIGHT - 20, settings.CAMERA_PREVIEW_WIDTH, settings.CAMERA_PREVIEW_HEIGHT)
        pygame.draw.rect(self.screen, (20, 30, 40), panel, border_radius=12)
        pygame.draw.rect(self.screen, (140, 180, 220, 200), panel, 2, border_radius=16)
        if self.camera_surface is not None:
            preview_size = (panel.width - 12, panel.height - 12)
            if self.camera_preview_surface is None:
                self.camera_preview_surface = pygame.transform.smoothscale(self.camera_surface, preview_size)
            self.screen.blit(self.camera_preview_surface, (panel.x + 6, panel.y + 6))
        if self._latest_camera_frame is None:
            status_text = self.camera_status
            while status_text and self.small_font.size(status_text)[0] > panel.width - 16:
                status_text = f"{status_text[:-4]}..." if len(status_text) > 4 else status_text[:-1]
            status = self.small_font.render(status_text, True, settings.CAMERA_STATUS_COLOR)
            status_rect = status.get_rect(center=panel.center)
            self.screen.blit(status, status_rect)

    def draw_menu(self):
        self.screen.fill((6, 8, 20))
        self.screen.blit(self.background, (0, 0))

        title = self.big_font.render("SPACE COMMANDER", True, (255, 255, 255))
        self.screen.blit(title, title.get_rect(center=(settings.GAME_WIDTH // 2, 175)))

        self.play_button.rect.center = (settings.GAME_WIDTH // 2 - 150, settings.GAME_HEIGHT // 2 + 40)
        self.tutorial_button.rect.center = (settings.GAME_WIDTH // 2 + 150, settings.GAME_HEIGHT // 2 + 40)
        mouse = self._window_to_game(pygame.mouse.get_pos())
        self.play_button.hovered = self.play_button.rect.collidepoint(mouse)
        self.tutorial_button.hovered = self.tutorial_button.rect.collidepoint(mouse)
        self.play_button.draw(self.screen)
        self.tutorial_button.draw(self.screen)

    def draw_tutorial(self):
        self.screen.fill((5, 10, 20))
        self.screen.blit(self.background, (0, 0))
        label = self.big_font.render("TUTORIAL", True, (255, 255, 255))
        self.screen.blit(label, label.get_rect(center=(settings.GAME_WIDTH // 2, 90)))
        text = [
            "LEFT HAND: Raise left index finger from pinch to move spaceship LEFT",
            "RIGHT HAND: Raise right index finger from pinch to move spaceship RIGHT",
            "The player does not fire manually.",
            "Spaceship automatically fires when enemies are detected.",
            "Enemies automatically fire when they detect the player.",
            "Destroy all normal enemies. The boss appears afterward.",
            "Defeat the boss to complete the mission.",
        ]
        for i, line in enumerate(text):
            surf = self.small_font.render(line, True, (230, 240, 255))
            self.screen.blit(surf, surf.get_rect(center=(settings.GAME_WIDTH // 2, 175 + i * 38)))
        self.back_button.rect.center = (settings.GAME_WIDTH // 2, settings.GAME_HEIGHT - 90)
        self.back_button.draw(self.screen)

    def draw_game_over(self):
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        title = self.big_font.render("GAME OVER", True, (255, 100, 100))
        self.screen.blit(title, title.get_rect(center=(settings.GAME_WIDTH // 2, 240)))
        score = self.font.render(f"SCORE: {self.score}", True, (255, 255, 255))
        self.screen.blit(score, score.get_rect(center=(settings.GAME_WIDTH // 2, 320)))
        self.retry_button.rect.center = (settings.GAME_WIDTH // 2 - 125, 430)
        self.main_menu_button.rect.center = (settings.GAME_WIDTH // 2 + 125, 430)
        self.retry_button.draw(self.screen)
        self.main_menu_button.draw(self.screen)

    def draw_victory(self):
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        title = self.big_font.render("BOSS DEFEATED", True, (140, 250, 150))
        self.screen.blit(title, title.get_rect(center=(settings.GAME_WIDTH // 2, 190)))
        title2 = self.big_font.render("MISSION COMPLETE", True, (255, 255, 255))
        self.screen.blit(title2, title2.get_rect(center=(settings.GAME_WIDTH // 2, 260)))
        score = self.font.render(f"SCORE: {self.score}", True, (255, 255, 255))
        self.screen.blit(score, score.get_rect(center=(settings.GAME_WIDTH // 2, 330)))
        self.main_menu_button.rect.center = (settings.GAME_WIDTH // 2, 430)
        self.main_menu_button.draw(self.screen)

    def draw_boss_warning(self):
        overlay = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        overlay.fill((25, 0, 0, 115))
        self.screen.blit(overlay, (0, 0))
        warning = self.big_font.render("BOSS INCOMING", True, (255, 100, 100))
        self.screen.blit(warning, warning.get_rect(center=(settings.GAME_WIDTH // 2, settings.GAME_HEIGHT // 2)))

    def _window_to_game(self, position):
        if not self.viewport_rect.collidepoint(position):
            return (-1, -1)
        scale = max(
            self.viewport_rect.width / settings.GAME_WIDTH,
            self.viewport_rect.height / settings.GAME_HEIGHT,
        )
        crop_x = (settings.GAME_WIDTH * scale - self.viewport_rect.width) / 2
        crop_y = (settings.GAME_HEIGHT * scale - self.viewport_rect.height) / 2
        x = (position[0] - self.viewport_rect.x + crop_x) / scale
        y = (position[1] - self.viewport_rect.y + crop_y) / scale
        return int(x), int(y)

    def _present_frame(self):
        window_width, window_height = self.window.get_size()
        if self.window_background_size != (window_width, window_height):
            self.window_background = self._cover_surface(self.background_source, (window_width, window_height))
            self.window_background_size = (window_width, window_height)
        scale = max(window_width / settings.GAME_WIDTH, window_height / settings.GAME_HEIGHT)
        scaled_width = max(1, int(settings.GAME_WIDTH * scale))
        scaled_height = max(1, int(settings.GAME_HEIGHT * scale))
        self.viewport_rect = self.window.get_rect()
        self.window.blit(self.window_background, (0, 0))
        if (scaled_width, scaled_height) == self.screen.get_size():
            frame = self.screen
        else:
            frame = pygame.transform.smoothscale(self.screen, (scaled_width, scaled_height))
        offset_x = int(random.uniform(-self.screen_shake, self.screen_shake) * scale) if self.screen_shake > 0 else 0
        offset_y = int(random.uniform(-self.screen_shake, self.screen_shake) * scale) if self.screen_shake > 0 else 0
        destination = (
            self.viewport_rect.x + (window_width - scaled_width) // 2 + offset_x,
            self.viewport_rect.y + (window_height - scaled_height) // 2 + offset_y,
        )
        self.window.blit(frame, destination)
        pygame.display.flip()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.VIDEORESIZE:
                width = max(800, event.w)
                height = max(533, event.h)
                self.window = pygame.display.set_mode((width, height), pygame.RESIZABLE)
            if event.type == pygame.MOUSEBUTTONDOWN:
                pos = self._window_to_game(event.pos)
                if self.state == "MAIN_MENU":
                    if self.play_button.is_clicked(pos):
                        self._start_game()
                    elif self.tutorial_button.is_clicked(pos):
                        self.state = "TUTORIAL"
                elif self.state == "TUTORIAL":
                    if self.back_button.is_clicked(pos):
                        self.state = "MAIN_MENU"
                elif self.state == "GAME_OVER":
                    if self.retry_button.is_clicked(pos):
                        self._start_game()
                    elif self.main_menu_button.is_clicked(pos):
                        self._stop_game_over_sound()
                        self._stop_laser_sounds()
                        self._clear_gameplay_state()
                        self.state = "MAIN_MENU"
                elif self.state == "VICTORY":
                    if self.main_menu_button.is_clicked(pos):
                        self._stop_game_over_sound()
                        self.state = "MAIN_MENU"
                        self.score = 0
        return True

    def run(self):
        self.draw_background(0)
        self.draw_menu()
        self.draw_camera_preview()
        self._present_frame()

        self.load_audio()
        self._start_camera_worker()
        running = True
        while running:
            dt = self.clock.tick(settings.FPS) / 1000.0
            running = self.handle_events()
            if not running:
                break

            hands = self._get_hand_state()
            if self.state == "MAIN_MENU":
                self.update_menu(dt, hands)
            elif self.state == "TUTORIAL":
                self.update_tutorial(dt, hands)
            elif self.state in {"PLAYING", "BOSS_INCOMING", "BOSS_FIGHT"}:
                self.update_playing(dt, hands)
            elif self.state == "GAME_OVER":
                self.update_game_over(dt, hands)
            else:
                self._update_transition_effects(dt)

            self._update_audio(dt)

            self.screen_shake = max(0.0, self.screen_shake - dt * 28.0)
            self.draw_background(dt)
            if self.state == "MAIN_MENU":
                self.draw_menu()
            elif self.state == "TUTORIAL":
                self.draw_tutorial()
            else:
                self.draw_gameplay()

            if self.state == "BOSS_INCOMING":
                self.draw_boss_warning()

            if self.state == "GAME_OVER":
                self.draw_game_over()
            elif self.state == "VICTORY":
                self.draw_victory()

            self.draw_camera_preview()
            self._present_frame()

        self._camera_stop.set()
        if self._camera_thread is not None:
            self._camera_thread.join(timeout=0.5)
        pygame.quit()


if __name__ == "__main__":
    Game().run()
