// endstop dimensions

$fn=100;

e_x=35;
e_y=11;
u_left=11.3;
u_right=17.7;
bh=28;
in=25.4;

m3=3.2/2;

z=3;


shift=e_x/2-z/2-u_right;
shift1=-e_x/2+z/2+u_left;
module top_stop(move=1,height=in+10){
difference(){
    union(){
        cube([e_x,e_y*2.5,z],center=true);
        translate([shift+move,0,height/2+z/2])
        cube([1.75,e_y*2.5,height],center=true);
//        translate([shift1,e_y,height/2+z/2])
//        cube([z,e_y,height],center=true);
    }
    
    translate([bh/2,0,-3])
    cylinder(100,m3,m3);
    translate([-bh/2,0,-3])
    cylinder(100,m3,m3);
}
}

module bracket(){
    difference(){
        cube([e_x+6,e_y,120],center=true);
        cube([e_x,e_y+3,120-6],center=true);
        translate([bh/2,0,-75])
        cylinder(150,m3,m3);
        translate([-bh/2,0,-75])
        cylinder(150,m3,m3);
    }
}

module bottom_stop() {
    difference(){
        union(){
            cube([40,40,3],center=true);
            translate([0,0,45/2])
            cube([40,2,45],center=true);
        }
        translate([10,-12.5,-5])
        cylinder(100,2.6,2.6);
        translate([-10,-12.5,-5])
        cylinder(100,2.6,2.6);
        translate([10,12.5,-5])
        cylinder(100,2.6,2.6);
        translate([-10,12.5,-5])
        cylinder(100,2.6,2.6);
        
    }
}
    
top_stop(1);

