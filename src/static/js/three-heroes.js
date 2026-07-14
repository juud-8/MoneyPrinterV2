/* Three.js hero scenes: Growth Terrain + Spend Constellation. */
(function (global) {
  const PALETTE = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#39c5cf"];

  let growthScene = null;
  let spendScene = null;
  let rafId = 0;
  let visible = true;
  let brandFilter = null;
  let onBrandSelect = null;

  function webglOk() {
    try {
      const canvas = document.createElement("canvas");
      return !!(canvas.getContext("webgl") || canvas.getContext("experimental-webgl"));
    } catch (e) {
      return false;
    }
  }

  function showFallback(id, message) {
    const card = document.getElementById(id)?.closest(".hero-card");
    if (!card) return;
    const fb = card.querySelector(".hero-fallback");
    if (fb) {
      fb.textContent = message || "WebGL unavailable — see 2D charts below.";
      fb.classList.add("visible");
    }
  }

  function disposeScene(state) {
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
  }

  function makeRenderer(container) {
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);
    return renderer;
  }

  function buildGrowth(overview) {
    const container = document.getElementById("growthTerrain");
    if (!container || typeof THREE === "undefined") return null;
    container.innerHTML = "";
    disposeScene(growthScene);

    const growth = overview.channel_growth || {};
    let brandIds = Object.keys(growth).filter((id) => (growth[id] || []).length >= 1);
    if (brandFilter) brandIds = brandIds.filter((id) => id === brandFilter);
    if (!brandIds.length) {
      showFallback("growthTerrain", "No channel snapshots yet — run Refresh YouTube metrics.");
      return null;
    }
    const fb = container.closest(".hero-card")?.querySelector(".hero-fallback");
    if (fb) fb.classList.remove("visible");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      42,
      container.clientWidth / Math.max(container.clientHeight, 1),
      0.1,
      100
    );
    camera.position.set(0, 4.2, 8.5);
    camera.lookAt(0, 0, 0);

    const renderer = makeRenderer(container);
    const group = new THREE.Group();
    scene.add(group);

    const ambient = new THREE.AmbientLight(0xffffff, 0.55);
    const dir = new THREE.DirectionalLight(0x9ecbff, 0.85);
    dir.position.set(3, 8, 4);
    scene.add(ambient, dir);

    brandIds.forEach((brandId, bi) => {
      const series = growth[brandId] || [];
      const values = series.map((p) => Number(p.subscribers) || 0);
      const max = Math.max(...values, 1);
      const points = [];
      values.forEach((v, i) => {
        const x = (i / Math.max(values.length - 1, 1)) * 8 - 4;
        const y = (v / max) * 2.4;
        const z = (bi - (brandIds.length - 1) / 2) * 1.15;
        points.push(new THREE.Vector3(x, y, z));
      });
      if (points.length === 1) {
        points.push(points[0].clone().add(new THREE.Vector3(0.4, 0, 0)));
      }
      const curve = new THREE.CatmullRomCurve3(points);
      const tube = new THREE.TubeGeometry(curve, Math.max(points.length * 8, 24), 0.08, 8, false);
      const mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(PALETTE[bi % PALETTE.length]),
        metalness: 0.2,
        roughness: 0.45,
        emissive: new THREE.Color(PALETTE[bi % PALETTE.length]),
        emissiveIntensity: 0.18,
      });
      const mesh = new THREE.Mesh(tube, mat);
      mesh.userData.brandId = brandId;
      group.add(mesh);

      const tip = points[points.length - 1];
      const tipMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.12, 12, 12),
        new THREE.MeshStandardMaterial({
          color: PALETTE[bi % PALETTE.length],
          emissive: PALETTE[bi % PALETTE.length],
          emissiveIntensity: 0.35,
        })
      );
      tipMesh.position.copy(tip);
      tipMesh.userData.brandId = brandId;
      group.add(tipMesh);
    });

    const grid = new THREE.GridHelper(10, 10, 0x30363d, 0x1f2733);
    grid.position.y = -0.05;
    scene.add(grid);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    renderer.domElement.addEventListener("click", (ev) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(group.children, true);
      if (hits.length && hits[0].object.userData.brandId && onBrandSelect) {
        onBrandSelect(hits[0].object.userData.brandId);
      }
    });

    growthScene = {
      scene,
      camera,
      renderer,
      group,
      container,
      t: 0,
    };
    return growthScene;
  }

  function buildSpend(overview) {
    const container = document.getElementById("spendConstellation");
    if (!container || typeof THREE === "undefined") return null;
    container.innerHTML = "";
    disposeScene(spendScene);

    let events = overview.recent_spend || [];
    if (brandFilter) events = events.filter((e) => e.brand_id === brandFilter);
    if (!events.length) {
      showFallback("spendConstellation", "No premium spend in this window.");
      return null;
    }
    const fb = container.closest(".hero-card")?.querySelector(".hero-fallback");
    if (fb) fb.classList.remove("visible");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      45,
      container.clientWidth / Math.max(container.clientHeight, 1),
      0.1,
      100
    );
    camera.position.set(0, 0, 7.5);

    const renderer = makeRenderer(container);
    const root = new THREE.Group();
    scene.add(root);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));

    const byBrand = {};
    events.forEach((e) => {
      const id = e.brand_id || "unknown";
      (byBrand[id] = byBrand[id] || []).push(e);
    });

    const brandIds = Object.keys(byBrand);
    const nodes = [];
    brandIds.forEach((brandId, bi) => {
      const color = new THREE.Color(PALETTE[bi % PALETTE.length]);
      const list = byBrand[brandId];
      list.forEach((e, i) => {
        const cost = Math.max(Number(e.cost_usd) || 0.05, 0.05);
        const radius = 0.08 + Math.min(Math.sqrt(cost) * 0.12, 0.45);
        const mesh = new THREE.Mesh(
          new THREE.SphereGeometry(radius, 14, 14),
          new THREE.MeshStandardMaterial({
            color,
            emissive: color,
            emissiveIntensity: 0.25,
            metalness: 0.15,
            roughness: 0.4,
          })
        );
        const angle = (i / Math.max(list.length, 1)) * Math.PI * 2 + bi;
        const orbit = 1.2 + bi * 0.55;
        mesh.position.set(Math.cos(angle) * orbit, (Math.sin(angle * 1.7) * 0.8), Math.sin(angle) * orbit);
        mesh.userData = { brandId, cost };
        root.add(mesh);
        nodes.push(mesh);
      });

      // faint brand ring
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(1.2 + bi * 0.55, 0.01, 8, 64),
        new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: 0.25 })
      );
      ring.rotation.x = Math.PI / 2.4;
      root.add(ring);
    });

    // link nodes of same brand lightly
    brandIds.forEach((brandId) => {
      const group = nodes.filter((n) => n.userData.brandId === brandId);
      for (let i = 1; i < group.length; i++) {
        const geo = new THREE.BufferGeometry().setFromPoints([
          group[i - 1].position,
          group[i].position,
        ]);
        const line = new THREE.Line(
          geo,
          new THREE.LineBasicMaterial({ color: 0x8b949e, transparent: true, opacity: 0.25 })
        );
        root.add(line);
      }
    });

    spendScene = { scene, camera, renderer, root, container, t: 0 };
    return spendScene;
  }

  function resize(state) {
    if (!state || !state.container) return;
    const w = state.container.clientWidth;
    const h = state.container.clientHeight;
    if (!w || !h) return;
    state.camera.aspect = w / h;
    state.camera.updateProjectionMatrix();
    state.renderer.setSize(w, h);
  }

  function tick() {
    rafId = requestAnimationFrame(tick);
    if (!visible) return;
    if (growthScene) {
      growthScene.t += 0.004;
      growthScene.group.rotation.y = Math.sin(growthScene.t) * 0.35;
      growthScene.group.rotation.x = 0.18;
      growthScene.renderer.render(growthScene.scene, growthScene.camera);
    }
    if (spendScene) {
      spendScene.t += 0.0035;
      spendScene.root.rotation.y = spendScene.t;
      spendScene.root.rotation.x = Math.sin(spendScene.t * 0.7) * 0.15;
      spendScene.renderer.render(spendScene.scene, spendScene.camera);
    }
  }

  function render(overview, options) {
    options = options || {};
    brandFilter = options.brandFilter || null;
    onBrandSelect = options.onBrandSelect || null;

    if (!webglOk() || typeof THREE === "undefined") {
      showFallback("growthTerrain");
      showFallback("spendConstellation");
      return;
    }

    buildGrowth(overview);
    buildSpend(overview);
    resize(growthScene);
    resize(spendScene);

    if (!rafId) tick();
  }

  function setVisible(v) {
    visible = !!v;
  }

  window.addEventListener("resize", () => {
    resize(growthScene);
    resize(spendScene);
  });

  document.addEventListener("visibilitychange", () => {
    setVisible(document.visibilityState === "visible");
  });

  global.MPHeroes = { render, setVisible, webglOk };
})(window);
