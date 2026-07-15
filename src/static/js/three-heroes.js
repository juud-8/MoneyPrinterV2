/* Growth Terrain — the single Three.js hero scene for EL JEFE mission control.
   Neon subscriber ribbons per brand over a holographic grid floor.
   Rebuilds only when the underlying data changes; parallax follows the pointer. */
(function (global) {
  const FALLBACK_COLORS = ["#46d7ff", "#3ddc97", "#f5b950", "#ff5c5c", "#b98aff", "#39c5cf"];
  const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  let state = null; // { scene, camera, renderer, group, container, meshes, t }
  let rafId = 0;
  let visible = true;
  let dataHash = "";
  let onBrandSelect = null;
  let hoveredBrand = null;
  let pointerTarget = { x: 0, y: 0 };
  let resizeObserver = null;

  function webglOk() {
    try {
      const canvas = document.createElement("canvas");
      return !!(canvas.getContext("webgl") || canvas.getContext("experimental-webgl"));
    } catch (e) {
      return false;
    }
  }

  function fallbackEl() {
    const card = document.getElementById("growthTerrain")?.closest(".hero-card");
    return card ? card.querySelector(".hero-fallback") : null;
  }

  function showFallback(message) {
    const fb = fallbackEl();
    if (fb) {
      fb.textContent = message || "WebGL unavailable — see 2D charts below.";
      fb.classList.add("visible");
    }
  }

  function hideFallback() {
    const fb = fallbackEl();
    if (fb) fb.classList.remove("visible");
  }

  function dispose() {
    if (!state) return;
    if (state.renderer) {
      state.renderer.dispose();
      const parent = state.renderer.domElement.parentNode;
      if (parent) parent.removeChild(state.renderer.domElement);
    }
    if (state.scene) {
      state.scene.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (Array.isArray(obj.material)) obj.material.forEach((m) => m.dispose());
          else obj.material.dispose();
        }
      });
    }
    state = null;
  }

  function build(overview, opts) {
    const container = document.getElementById("growthTerrain");
    if (!container || typeof THREE === "undefined") return;

    const growth = overview.channel_growth || {};
    let brandIds = Object.keys(growth)
      .filter((id) => (growth[id] || []).length >= 1)
      .sort();
    if (opts.brandFilter) brandIds = brandIds.filter((id) => id === opts.brandFilter);
    if (!brandIds.length) {
      dispose();
      container.innerHTML = "";
      showFallback("No channel snapshots yet — hit ⟳ Metrics to start the terrain.");
      return;
    }
    hideFallback();
    container.innerHTML = "";
    dispose();

    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x04070d, 10, 20);

    const camera = new THREE.PerspectiveCamera(
      40,
      container.clientWidth / Math.max(container.clientHeight, 1),
      0.1,
      100
    );
    camera.position.set(0, 3.6, 9.2);
    camera.lookAt(0, 0.8, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);

    const group = new THREE.Group();
    scene.add(group);

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const key = new THREE.DirectionalLight(0x9ecbff, 0.9);
    key.position.set(3, 8, 5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf5b950, 0.25);
    rim.position.set(-4, 3, -4);
    scene.add(rim);

    // Shared vertical scale across brands so ribbons are comparable.
    let globalMax = 1;
    for (const id of brandIds) {
      for (const p of growth[id] || []) {
        globalMax = Math.max(globalMax, Number(p.subscribers) || 0);
      }
    }

    const laneGap = Math.min(1.3, 4.2 / Math.max(brandIds.length, 1));
    const meshes = [];

    brandIds.forEach((brandId, bi) => {
      const colorHex = (opts.colors && opts.colors[brandId]) || FALLBACK_COLORS[bi % FALLBACK_COLORS.length];
      const color = new THREE.Color(colorHex);
      const series = growth[brandId] || [];
      const values = series.map((p) => Number(p.subscribers) || 0);
      const z = (bi - (brandIds.length - 1) / 2) * laneGap;

      const points = values.map((v, i) => {
        const x = (i / Math.max(values.length - 1, 1)) * 10 - 5;
        const y = 0.12 + (v / globalMax) * 2.6;
        return new THREE.Vector3(x, y, z);
      });
      if (points.length === 1) points.push(points[0].clone().add(new THREE.Vector3(0.5, 0, 0)));

      // Ribbon tube
      const curve = new THREE.CatmullRomCurve3(points);
      const tube = new THREE.TubeGeometry(curve, Math.max(points.length * 8, 32), 0.055, 8, false);
      const mat = new THREE.MeshStandardMaterial({
        color,
        metalness: 0.25,
        roughness: 0.35,
        emissive: color,
        emissiveIntensity: 0.35,
      });
      const mesh = new THREE.Mesh(tube, mat);
      mesh.userData.brandId = brandId;
      group.add(mesh);
      meshes.push(mesh);

      // Translucent curtain from the ribbon down to the floor
      const curtainPts = curve.getPoints(Math.max(points.length * 6, 24));
      const positions = new Float32Array(curtainPts.length * 2 * 3);
      curtainPts.forEach((p, i) => {
        positions.set([p.x, p.y, p.z], i * 6);
        positions.set([p.x, 0, p.z], i * 6 + 3);
      });
      const indices = [];
      for (let i = 0; i < curtainPts.length - 1; i++) {
        const a = i * 2, b = i * 2 + 1, c = i * 2 + 2, d = i * 2 + 3;
        indices.push(a, b, c, b, d, c);
      }
      const curtainGeo = new THREE.BufferGeometry();
      curtainGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      curtainGeo.setIndex(indices);
      const curtain = new THREE.Mesh(
        curtainGeo,
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.1,
          side: THREE.DoubleSide,
          depthWrite: false,
        })
      );
      curtain.userData.brandId = brandId;
      group.add(curtain);
      meshes.push(curtain);

      // Glowing tip at "now"
      const tip = points[points.length - 1];
      const tipMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.11, 14, 14),
        new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.9 })
      );
      tipMesh.position.copy(tip);
      tipMesh.userData.brandId = brandId;
      group.add(tipMesh);
      meshes.push(tipMesh);
    });

    const grid = new THREE.GridHelper(14, 22, 0x1e4a66, 0x102436);
    grid.position.y = 0;
    group.add(grid);

    // Pointer interactivity: parallax + hover highlight + click-to-focus.
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    function pick(ev) {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(meshes, false);
      return hits.length ? hits[0].object.userData.brandId : null;
    }

    renderer.domElement.addEventListener("mousemove", (ev) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointerTarget.x = ((ev.clientX - rect.left) / rect.width - 0.5) * 2;
      pointerTarget.y = ((ev.clientY - rect.top) / rect.height - 0.5) * 2;
      const brand = pick(ev);
      renderer.domElement.style.cursor = brand ? "pointer" : "default";
      if (brand !== hoveredBrand) {
        hoveredBrand = brand;
        for (const m of meshes) {
          if (!m.material || m.material.emissiveIntensity === undefined) continue;
          const isTube = m.geometry && m.geometry.type === "TubeGeometry";
          const base = isTube ? 0.35 : 0.9;
          m.material.emissiveIntensity = hoveredBrand && m.userData.brandId === hoveredBrand ? base + 0.45 : base;
        }
        if (REDUCED) renderOnce();
      }
    });

    renderer.domElement.addEventListener("mouseleave", () => {
      pointerTarget.x = 0;
      pointerTarget.y = 0;
      hoveredBrand = null;
    });

    renderer.domElement.addEventListener("click", (ev) => {
      const brand = pick(ev);
      if (brand && onBrandSelect) onBrandSelect(brand);
    });

    state = { scene, camera, renderer, group, container, t: Math.random() * 10 };

    if (resizeObserver) resizeObserver.disconnect();
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => resize());
      resizeObserver.observe(container);
    }

    if (REDUCED) {
      group.rotation.x = 0.12;
      renderOnce();
    } else if (!rafId) {
      tick();
    }
  }

  function resize() {
    if (!state || !state.container) return;
    const w = state.container.clientWidth;
    const h = state.container.clientHeight;
    if (!w || !h) return;
    state.camera.aspect = w / h;
    state.camera.updateProjectionMatrix();
    state.renderer.setSize(w, h);
    if (REDUCED) renderOnce();
  }

  function renderOnce() {
    if (state) state.renderer.render(state.scene, state.camera);
  }

  function tick() {
    rafId = requestAnimationFrame(tick);
    if (!visible || !state) return;
    state.t += 0.003;
    const driftY = Math.sin(state.t) * 0.06;
    const targetY = driftY + pointerTarget.x * 0.22;
    const targetX = 0.12 + pointerTarget.y * 0.08;
    state.group.rotation.y += (targetY - state.group.rotation.y) * 0.06;
    state.group.rotation.x += (targetX - state.group.rotation.x) * 0.06;
    state.renderer.render(state.scene, state.camera);
  }

  function render(overview, options) {
    options = options || {};
    onBrandSelect = options.onBrandSelect || null;

    if (!webglOk() || typeof THREE === "undefined") {
      showFallback();
      return;
    }

    const hash = JSON.stringify([overview.channel_growth || {}, options.brandFilter || null, options.colors || {}]);
    if (hash === dataHash && state) {
      resize();
      return; // same data — keep the live scene, no rebuild flicker
    }
    dataHash = hash;
    build(overview, options);
  }

  function setVisible(v) {
    visible = !!v;
  }

  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", () => {
    setVisible(document.visibilityState === "visible");
  });

  global.MPHeroes = { render, setVisible, webglOk };
})(window);
