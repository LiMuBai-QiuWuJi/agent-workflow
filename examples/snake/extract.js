
  /* ---------------- 每次前进一格 ---------------- */
  function step() {
    if (state !== 'running') return;

    if (pendingDirs.length) dir = pendingDirs.shift();

    var head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };

    // 撞墙
    if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS) {
      gameOver(false);
      return;
    }

    var eating = !!food && head.x === food.x && head.y === food.y;

    // 撞自身：不吃食物时尾巴那格会腾空，允许进入
    var body = eating ? snake : snake.slice(0, snake.length - 1);
    for (var i = 0; i < body.length; i++) {
      if (body[i].x === head.x && body[i].y === head.y) {
        gameOver(false);
        return;
      }
    }

    snake.unshift(head);

    if (eating) {
      score += 1;                       // 吃到食物：身体加长 1 节 + 得分加 1
      scoreEl.textContent = String(score);
      placeFood();
      if (!food) {                      // 网格被吃满：胜利结算
        gameOver(true);
        return;
      }
    } else {
      snake.pop();
    }

    draw();
  }

  /* ---------------- 游戏结束 ---------------- */
  function gameOver(win) {
    state = 'over';
    isWin = !!win;
    stopTimer();                        // 游戏结束：计时暂停
    setOverlay();
    draw();
  }

  /* ---------------- 遮罩与按钮 ---------------- */
  function setOverlay() {
    if (state === 'running') {
      overlay.classList.remove('show');
      restartBtn.classList.add('hidden');
      return;
    }

    overlay.classList.add('show');

    if (state === 'ready') {
      overlayMsg.textContent = '准备开始';
      overlaySub.textContent = '按 ↑ ↓ ← → 控制蛇的方向';
      restartBtn.classList.add('hidden');
    } else {
      overlayMsg.textContent = isWin ? '恭喜通关！' : '游戏结束';
      overlaySub.textContent = '本局得分：' + score;
      restartBtn.classList.remove('hidden');
    }
  }

  /* ---------------- 绘制 ---------------- */
  function draw() {
    var W = canvas.width;
    var H = canvas.height;
    var i;

    ctx.fillStyle = '#f8fafc';
    ctx.fillRect(0, 0, W, H);

    // 网格线
    ctx.strokeStyle = 'rgba(15, 23, 42, .07)';
    ctx.lineWidth = 1;
    for (i = 1; i < COLS; i++) {
      ctx.beginPath();
      ctx.moveTo(i * CELL + 0.5, 0);
      ctx.lineTo(i * CELL + 0.5, H);
      ctx.stroke();
    }
    for (i = 1; i < ROWS; i++) {
      ctx.beginPath();
      ctx.moveTo(0, i * CELL + 0.5);
      ctx.lineTo(W, i * CELL + 0.5);
      ctx.stroke();
    }

    // 食物
    if (food) {
      var fx = food.x * CELL + CELL / 2;
      var fy = food.y * CELL + CELL / 2;
      ctx.beginPath();
      ctx.arc(fx, fy, CELL * 0.42, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(239, 68, 68, .18)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(fx, fy, CELL * 0.30, 0, Math.PI * 2);
      ctx.fillStyle = '#ef4444';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(fx - CELL * 0.09, fy - CELL * 0.09, CELL * 0.08, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255, 255, 255, .85)';
      ctx.fill();
    }

    // 蛇身（从尾到头绘制，保证蛇头在最上层）
    for (i = snake.length - 1; i >= 0; i--) {
      var s = snake[i];
      var pad = i === 0 ? 1 : 1.5;
      var x = s.x * CELL + pad;
      var y = s.y * CELL + pad;
      var size = CELL - pad * 2;

      roundRect(x, y, size, size, i === 0 ? 7 : 5);
      ctx.fillStyle = i === 0 ? '#15803d' : (i % 2 === 0 ? '#22c55e' : '#34d399');
      ctx.fill();
    }

    // 蛇头眼睛（朝向当前方向）
    if (snake.length) {
      var h = snake[0];
      var cx = h.x * CELL + CELL / 2;
      var cy = h.y * CELL + CELL / 2;
      var off = CELL * 0.20;
      var eyeR = CELL * 0.10;
      var e1x = cx + (dir.y !== 0 ? -off : off * dir.x);
      var e1y = cy + (dir.x !== 0 ? -off : off * dir.y);
      var e2x = cx + (dir.y !== 0 ?  off : off * dir.x);
      var e2y = cy + (dir.x !== 0 ?  off : off * dir.y);

      ctx.fillStyle = '#f8fafc';
      ctx.beginPath(); ctx.arc(e1x, e1y, eyeR, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(e2x, e2y, eyeR, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#0f172a';
      ctx.beginPath(); ctx.arc(e1x, e1y, eyeR * 0.5, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.arc(e2x, e2y, eyeR * 0.5, 0, Math.PI * 2); ctx.fill();
    }
  }

  /* ---------------- 事件 ---------------- */
  function onKeyDown(e) {
    var name = e.key;

    if (Object.prototype.hasOwnProperty.call(DIRS, name)) {
      e.preventDefault();                 // 阻止页面滚动

      if (state === 'over') return;      // 已结束：需点击「重新开始」

      if (state === 'ready') {           // 首次按方向键即开始，并启动计时
        state = 'running';
        setOverlay();
        startTimer();
      }

      changeDir(name);
    }
  }

  function onRestart() {
    reset();                              // 重置为初始状态（未开始、计时暂停）
  }

  document.addEventListener('keydown', onKeyDown);
  restartBtn.addEventListener('click', onRestart);

  reset();
})();
