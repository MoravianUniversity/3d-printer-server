/**
 * parameters = {
 *  color: <hex>,
 *  linewidth: <float>,
 *  resolution: <Vector2>, // to be set by renderer
 * }
 */

import {
	ShaderLib,
	ShaderMaterial,
	UniformsLib,
	UniformsUtils,
	Vector2
//} from "../../../build/three.module.js";
} from 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@r134/build/three.module.min.js';


UniformsLib.line = {
	linewidth: { value: 1 },
	resolution: { value: new Vector2( 1, 1 ) },
};

ShaderLib[ 'line' ] = {

	uniforms: UniformsUtils.merge( [
		UniformsLib.common,
		UniformsLib.fog,
		UniformsLib.line
	] ),

	vertexShader:
		/* glsl */`
		#include <common>
		#include <color_pars_vertex>
		#include <fog_pars_vertex>
		#include <logdepthbuf_pars_vertex>
		#include <clipping_planes_pars_vertex>
        
		uniform float linewidth;
		uniform vec2 resolution;
		attribute vec3 instanceStart;
		attribute vec3 instanceEnd;
		attribute vec3 instanceColorStart;
		attribute vec3 instanceColorEnd;
		//varying vec2 vUv;
		varying vec4 worldPos;
		varying vec3 worldStart;
		varying vec3 worldEnd;
		varying vec3 vNormal;
		varying vec3 vLight;

		void trimSegment( const in vec4 start, inout vec4 end ) {
			// trim end segment so it terminates between the camera plane and the near plane
			// conservative estimate of the near plane
			float a = projectionMatrix[ 2 ][ 2 ]; // 3nd entry in 3th column
			float b = projectionMatrix[ 3 ][ 2 ]; // 3nd entry in 4th column
			float nearEstimate = - 0.5 * b / a;
			float alpha = ( nearEstimate - start.z ) / ( end.z - start.z );
			end.xyz = mix( start.xyz, end.xyz, alpha );
		}
		void main() {
			#ifdef USE_COLOR
				vColor.xyz = ( position.y < 0.5 ) ? instanceColorStart : instanceColorEnd;
			#endif
			float aspect = resolution.x / resolution.y;
			//vUv = uv;
			// camera space
			vec4 start = modelViewMatrix * vec4( instanceStart, 1.0 );
			vec4 end = modelViewMatrix * vec4( instanceEnd, 1.0 );
			// special case for perspective projection, and segments that terminate either in, or behind, the camera plane
			// clearly the gpu firmware has a way of addressing this issue when projecting into ndc space
			// but we need to perform ndc-space calculations in the shader, so we must address this issue directly
			// perhaps there is a more elegant solution -- WestLangley
			bool perspective = ( projectionMatrix[ 2 ][ 3 ] == - 1.0 ); // 4th entry in the 3rd column
			if ( perspective ) {
				if ( start.z < 0.0 && end.z >= 0.0 ) {
					trimSegment( start, end );
				} else if ( end.z < 0.0 && start.z >= 0.0 ) {
					trimSegment( end, start );
				}
			}
			// clip space
			vec4 clipStart = projectionMatrix * start;
			vec4 clipEnd = projectionMatrix * end;
			// ndc space
			vec3 ndcStart = clipStart.xyz / clipStart.w;
			vec3 ndcEnd = clipEnd.xyz / clipEnd.w;
			// direction
			vec2 dir = ndcEnd.xy - ndcStart.xy;
			// account for clip-space aspect ratio
			dir.x *= aspect;
			dir = normalize( dir );

			// get the offset direction as perpendicular to the view vector
			vec3 worldDir = normalize( end.xyz - start.xyz );
			vec3 offset;
			if ( position.y < 0.5 ) {
				offset = normalize( cross( start.xyz, worldDir ) );
			} else {
				offset = normalize( cross( end.xyz, worldDir ) );
			}
			// sign flip
			if ( position.x < 0.0 ) offset *= - 1.0;
			float forwardOffset = dot( worldDir, vec3( 0.0, 0.0, 1.0 ) );
			// endcaps
			if ( position.y > 1.0 || position.y < 0.0 ) {
				offset.xy += dir * 2.0 * forwardOffset;
			}
			// adjust for linewidth
			offset *= linewidth * 0.5;
			// set the world position
			worldPos = ( position.y < 0.5 ) ? start : end;
			worldPos.xyz += offset;
			// project the worldpos
			vec4 clip = projectionMatrix * worldPos;
			// shift the depth of the projected points so the line
			// segments overlap neatly
			vec3 clipPose = ( position.y < 0.5 ) ? ndcStart : ndcEnd;
			clip.z = clipPose.z * clip.w;

			gl_Position = clip;
			vec4 mvPosition = ( position.y < 0.5 ) ? start : end; // this is an approximation



			// --------------------
			// Fake normals for lighting equations
			vNormal = offset.xyz;
			vec3 lightPos = vec3(1000, 1000, 1000);
			vLight = normalize(lightPos - clip.xyz);
			// --------------------

			#include <logdepthbuf_vertex>
			#include <clipping_planes_vertex>
    		#include <fog_vertex>
		}
		`,

	fragmentShader:
		/* glsl */`
		uniform vec3 diffuse;
		uniform float opacity;
		uniform float linewidth;

		#include <common>
		#include <color_pars_fragment>
		#include <fog_pars_fragment>
		#include <logdepthbuf_pars_fragment>
		#include <clipping_planes_pars_fragment>

		varying vec4 worldPos;
		varying vec3 worldStart;
		varying vec3 worldEnd;
		//varying vec2 vUv;
		varying vec3 vNormal;
		varying vec3 vLight;

		vec2 closestLineToLine(vec3 p1, vec3 p2, vec3 p3, vec3 p4) {
			float mua;
			float mub;
			vec3 p13 = p1 - p3;
			vec3 p43 = p4 - p3;
			vec3 p21 = p2 - p1;
			float d1343 = dot( p13, p43 );
			float d4321 = dot( p43, p21 );
			float d1321 = dot( p13, p21 );
			float d4343 = dot( p43, p43 );
			float d2121 = dot( p21, p21 );
			float denom = d2121 * d4343 - d4321 * d4321;
			float numer = d1343 * d4321 - d1321 * d4343;
			mua = numer / denom;
			mua = clamp( mua, 0.0, 1.0 );
			mub = ( d1343 + d4321 * ( mua ) ) / d4343;
			mub = clamp( mub, 0.0, 1.0 );
			return vec2( mua, mub );
		}

		void main() {
			#include <clipping_planes_fragment>
			float alpha = opacity;

			// Find the closest points on the view ray and the line segment
			vec3 rayEnd = normalize( worldPos.xyz ) * 1e5;
			vec3 lineDir = worldEnd - worldStart;
			vec2 params = closestLineToLine( worldStart, worldEnd, vec3( 0.0, 0.0, 0.0 ), rayEnd );
			vec3 p1 = worldStart + lineDir * params.x;
			vec3 p2 = rayEnd * params.y;
			vec3 delta = p1 - p2;
			float len = length( delta );
			float norm = len / linewidth;
			#ifdef ALPHA_TO_COVERAGE
				float dnorm = fwidth( norm );
				alpha = 1.0 - smoothstep( 0.5 - dnorm, 0.5 + dnorm, norm );
			#else
				if ( norm > 0.5 ) { discard; }
			#endif



			// --------------------

			float lambertian = max(dot(vNormal, vLight), 0.0)*12.0;
			vec3 color = diffuse * (0.5 + lambertian);
			vec4 diffuseColor = vec4( color, alpha );

			// --------------------



			#include <logdepthbuf_fragment>
			#include <color_fragment>
			gl_FragColor = vec4( diffuseColor.rgb, alpha );
			#include <tonemapping_fragment>
			#include <encodings_fragment>
			#include <fog_fragment>
			#include <premultiplied_alpha_fragment>
		}
		`
};

class LineMaterial extends ShaderMaterial {

	constructor( parameters ) {

		super( {

			type: 'LineMaterial',

			uniforms: UniformsUtils.clone( ShaderLib[ 'line' ].uniforms ),

			vertexShader: ShaderLib[ 'line' ].vertexShader,
			fragmentShader: ShaderLib[ 'line' ].fragmentShader,

			clipping: true // required for clipping support

		} );

		Object.defineProperties( this, {

			color: {

				enumerable: true,

				get: function () {

					return this.uniforms.diffuse.value;

				},

				set: function ( value ) {

					this.uniforms.diffuse.value = value;

				}

			},

			linewidth: {

				enumerable: true,

				get: function () {

					return this.uniforms.linewidth.value;

				},

				set: function ( value ) {

					this.uniforms.linewidth.value = value;

				}

			},

			opacity: {

				enumerable: true,

				get: function () {

					return this.uniforms.opacity.value;

				},

				set: function ( value ) {

					this.uniforms.opacity.value = value;

				}

			},

			resolution: {

				enumerable: true,

				get: function () {

					return this.uniforms.resolution.value;

				},

				set: function ( value ) {

					this.uniforms.resolution.value.copy( value );

				}

			},

			alphaToCoverage: {

				enumerable: true,

				get: function () {

					return Boolean( 'ALPHA_TO_COVERAGE' in this.defines );

				},

				set: function ( value ) {

					if ( Boolean( value ) !== Boolean( 'ALPHA_TO_COVERAGE' in this.defines ) ) {

						this.needsUpdate = true;

					}

					if ( value === true ) {

						this.defines.ALPHA_TO_COVERAGE = '';
						this.extensions.derivatives = true;

					} else {

						delete this.defines.ALPHA_TO_COVERAGE;
						this.extensions.derivatives = false;

					}

				}

			}

		} );

		this.setValues( parameters );

	}

}

LineMaterial.prototype.isLineMaterial = true;

export { LineMaterial };
