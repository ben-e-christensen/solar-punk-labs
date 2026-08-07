$fn=100;

w=20;
l=40;
lv=50;
m5=2.6;
h=3;

module face(vert=false){
    if(vert){
        translate([0,l/2-h/2,lv/2-h/2])
        rotate([90,0,0])
        difference(){
        cube([w,lv,h],center=true);
        
        for(i=[0:1]){
            translate([0, lv/2-10-(i*20),-4])
            cylinder(100,r=m5);
            }
        
    }
    }
    else {
    difference(){
        cube([w,l,h],center=true);
        
        for(i=[0:1]){
            translate([0, l/2-10-(i*20),-4])
            cylinder(100,r=m5);
        }
    }
}
}

face();
face(true);