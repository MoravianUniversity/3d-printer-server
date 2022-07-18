import * as THREE from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r134/build/three.module.min.js';

import Stats from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r134/examples/jsm/libs/stats.module.js';

import { LineSegments2 } from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r134/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r134/examples/jsm/lines/LineSegmentsGeometry.js';
//import { LineMaterial } from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r134/examples/jsm/lines/LineMaterial.js';
import { LineMaterial } from './LineMaterial.js';

/** Fully clears a Three JS object freeing all of its memory. */
function clearObject(obj) {
    while (obj.children.length > 0) {
        clearThree(obj.children[0]);
        obj.remove(obj.children[0]);
    }
    if (obj.geometry) {
        obj.geometry.dispose();
    }
    if (obj.material) {
        Object.keys(obj.material).forEach(prop => {
            if(obj.material[prop] && typeof obj.material[prop].dispose === 'function')
                obj.material[prop].dispose();                                                      
        });
        obj.material.dispose();
    }
}

/** The colors used by the displays. */
const COLORS = {
    printed: [
        { color: new THREE.Vector3(0.8, 0.8, 0.8), hex: 0xCCCCCC, opacity: 1 }, // light gray
        { color: new THREE.Vector3(0.6, 0.6, 0.8), hex: 0x9999CC, opacity: 1 }, // light blue
    ],
    printing: [
        { color: new THREE.Vector3(0.8, 0.0, 0.0), hex: 0xCC0000, opacity: 1 }, // red
        { color: new THREE.Vector3(0.8, 0.0, 0.0), hex: 0xCC0000, opacity: 1 },
    ],
    future: [
        { color: new THREE.Vector3(0.8, 0.8, 0.8), hex: 0xCCCCCC, opacity: 0.3 }, // transparent light gray
        { color: new THREE.Vector3(0.6, 0.6, 0.8), hex: 0x9999CC, opacity: 0.3 }, // transparent light blue
    ]
}

class ModelViewer {
    constructor(canvas) {
        // Set the rendering
        let [w, h] = [canvas.width, canvas.height];
        this.renderer = new THREE.WebGLRenderer({antialias: true, canvas: canvas});
        this.renderer.setPixelRatio(window.devicePixelRatio);
        this.renderer.setClearColor(0x000000, 1.0);
        this.renderer.sortObjects = false; // TODO: for efficiency, but for transparency sorting may be required?
        this.camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 1000);
        this.scene = new THREE.Scene();

        new ResizeObserver(this.resized.bind(this)).observe(canvas); // if that stops working, just use: this.resized();

        this.stats = new Stats();

        return this;
    }

    /**
     * Called automatically whenever the canvas is resized. For older browsers this may
     * need to be called manually.
     */
    resized() {
        let [w, h] = [this.renderer.domElement.width, this.renderer.domElement.height];
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w / window.devicePixelRatio, h / window.devicePixelRatio);
        this.renderer.setViewport(0, 0, w / window.devicePixelRatio, h / window.devicePixelRatio);
        if (this.layers) {
            for (const core in this.layers) {
                for (const line of this.layers[core].values()) {
                    line.material.resolution.set(w, h);
                }
            }
        }
    }

    /**
     * Call this once to begin animating the display.
     * DO NOT call this a second time ever.
     * The animation cannot be stopped.
     */
    animate() {
        requestAnimationFrame(this.animate.bind(this));

        // Rotate with time
        const timer = performance.now();
        this.scene.rotation.x = timer*0.0005;
        this.scene.rotation.y = timer*0.0002;

        this.stats.update();
        this.renderer.render(this.scene, this.camera);
    }

    /**
     * Set the current data for the display. The data is an object with a single key
     * of "layers" which is an array with one object for each core. Each of those
     * objects have 3 propertues: height (a float), z (a float), and lines (an array
     * of arrays of 2-element array of floats).
     */
    set_data(data) {
        this.layers = []; // core -> z value -> LineSegments2 object (temporarily an array of point values)
        this.current_printing_z = 10000;

        // Get Position Data
        let min_z = 10000, max_z = -10000;
        for (const core in data.layers) {
            this.layers.push(new Map());
            for (const layer of data.layers[core]) {
                const z = layer.z;
                if (!this.layers[core].has(z)) {
                    this.layers[core].set(z, []);
                }
                const layer_pts = this.layers[core].get(z);
                layer_pts.height = layer.height;
                const lh_half = layer.height/2;
                if (z-lh_half < min_z) { min_z = z-lh_half; }
                if (z+lh_half > max_z) { max_z = z+lh_half; }
                for (const line of layer.lines) {
                    for (let i = 1; i < line.length; i++) {
                        layer_pts.push(...line[i-1]);
                        layer_pts.push(z);
                        layer_pts.push(...line[i]);
                        layer_pts.push(z);
                    }
                }
            }
        }

        // Reset the scene
        clearObject(this.scene);
        this.group = new THREE.Group();
        this.scene.add(this.group);

        // Create all of the geometries
        for (const core in this.layers) {
            const color = COLORS.printed[core].hex, opacity = COLORS.printed[core].opacity;
            for (const [z, layer_pts] of this.layers[core].entries()) {
                const geometry = new LineSegmentsGeometry();
                geometry.setPositions(layer_pts);
                const layer = new LineSegments2(geometry, new LineMaterial({
                    color: color,
                    linewidth: layer_pts.height, // TODO: width vs height
                    opacity: opacity,
                    transparent: true,
                    // worldUnits: true, // if using the original LineMaterial, need this. It is hard-coded in the modified one.
                }));
                layer.computeLineDistances();
                this.group.add(layer);
                this.layers[core].set(z, layer);
            }
        }

        // Center the model and scale
        // NOTE: for some reason the z coordinate (and to a lesser degree y and sometimes x)
        // are computed incorrectly by Box3, we fix the z here (and hope the others are much less severe).
        const bbox = new THREE.Box3().setFromObject(this.group);
        bbox.max.z = max_z; bbox.min.z = min_z;
        const center = bbox.min.clone().lerp(bbox.max, 0.5);
        this.group.position.copy(center).negate();
        this.camera.position.set(0, 0, bbox.max.distanceTo(center) * 1.5);

        this.resized(); // to update the resolutions of the materials
    }

    /**
     * When the z level changes, update the colors of the layers appropriately.
     */
    set_printing_z(new_printing_z) {
        if (new_printing_z === this.current_printing_z) { return; }
        const cur_z = this.current_printing_z;
        for (const core in this.layers) {
            for (const [z, layer] of this.layers[core].entries()) {
                const lh_half = layer.material.linewidth/2;
                let color;
                if (z - lh_half <= new_printing_z && z + lh_half >= new_printing_z) {
                    color = COLORS.printing[core];
                } else if (z < new_printing_z) {
                    color = COLORS.printed[core];
                } else { // z > new_printing_z
                    color = COLORS.future[core];
                }
                if (layer.material.color != color.color || layer.material.opacity != color.opacity) {
                    layer.material.color = color.color;
                    layer.material.opacity = color.opacity;
                }
            }
        }
        this.current_printing_z = new_printing_z;
    }
}

// Export the ModelViewer class, both to other modules and to non-modules
export { ModelViewer };
window.ModelViewer = ModelViewer;
