import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import sys
import os

def main():
    csv_path = 'out/magent2.csv'
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
        
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found. Run 'make magnet2' first.")
        sys.exit(1)
    
    # Load data
    # format: i.x, i.y, i.z, j.x, j.y, j.z
    # i is Cartesian (x, y, z), j is Cylindrical (phi, r, high)
    names = ['x', 'y', 'z', 'phi', 'r', 'high']
    try:
        df = pd.read_csv(csv_path, names=names)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        sys.exit(1)

    # Use a dark, professional theme
    plt.style.use('dark_background')
    fig = plt.figure(figsize=(16, 8))
    
    # 1. 3D Cartesian View
    ax1 = fig.add_subplot(121, projection='3d')
    # Use color to represent phi (angle) to see the winding
    p1 = ax1.scatter(df['x'], df['y'], df['z'], c=df['phi'], cmap='hsv', s=1, alpha=0.5)
    ax1.set_title('Coils 3D (Cartesian)', fontsize=14, pad=20)
    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax1.set_zlabel('Z')
    # Keep aspect ratio equal for 3D
    ax1.set_box_aspect([1, 1, 0.6]) 
    
    fig.colorbar(p1, ax=ax1, label='Phi (rad)', shrink=0.6, pad=0.1)

    # 2. 2D Unrolled View (Phi-Z)
    ax2 = fig.add_subplot(122)
    # Use color to represent radius
    p2 = ax2.scatter(df['phi'], df['high'], c=df['r'], cmap='viridis', s=2, alpha=0.6)
    ax2.set_title('Coils Unrolled (Phi vs Z)', fontsize=14, pad=20)
    ax2.set_xlabel('Phi (radians)')
    ax2.set_ylabel('Z (height)')
    
    fig.colorbar(p2, ax=ax2, label='Radius (r)', shrink=0.8)
    
    # Add grid
    ax2.grid(True, linestyle='--', alpha=0.2)
    
    plt.suptitle(f'Magnet2 Coil Visualization ({os.path.basename(csv_path)})', fontsize=18, y=0.98)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    # Save the figure
    os.makedirs('out', exist_ok=True)
    output_img = 'out/coils_view.png'
    plt.savefig(output_img, dpi=200)
    print(f"Saved visualization to {output_img}")
    
    plt.show()

if __name__ == "__main__":
    main()
